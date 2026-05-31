from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime
from typing import Optional

import anthropic
from rich.console import Console

from agents.market_analysis import MarketAnalysisAgent
from agents.strategy_selector import StrategySelectorAgent
from agents.strategy_reviewer import StrategyReviewerAgent
from agents.news_agent import NewsAgent
from agents.confirmation_agent import ConfirmationAgent
from agents.execution_agent import ExecutionAgent
from agents.risk_manager import RiskManagerAgent
from config import Settings
from models.agent_output import (
    PipelineContext, StrategyProposal, ReviewDecision,
    NewsAssessment, ConfirmationDecision,
)
from models.market_state import MarketState, TechnicalIndicators, Trend
from models.trade import LiveTrade, TradeSignal, TradeDirection, TradeStatus
from tools.market_data import MockMarketDataProvider
from tools.news_tools import MockNewsProvider
from tools.trading_tools import MockBroker
from utils.dashboard import TradingDashboard
from utils.logger import get_logger
from utils.pip_calculator import calculate_sl_price, calculate_tp_price, price_to_pips


class MasterAgent:
    def __init__(self, settings: Settings, console: Console):
        self.settings = settings
        self.console = console
        self.logger = get_logger("MasterAgent")

        if settings.live_trading:
            # Live mode — real MT5 data and broker
            from tools.mt5_market_data import MT5MarketDataProvider
            from tools.mt5_broker import MT5Broker
            self.market_provider = MT5MarketDataProvider()
            self.news_provider = MockNewsProvider(scenario="bullish")  # news always mock
            self.broker = MT5Broker(
                login=settings.mt5_login,
                password=settings.mt5_password,
                server=settings.mt5_server,
                magic=settings.mt5_magic,
                lot_size=settings.mt5_lot_size,
            )
            self._live = True
        else:
            # Mock mode — safe for testing
            self.market_provider = MockMarketDataProvider(scenario=settings.mock_scenario)
            self.news_provider = MockNewsProvider(scenario=settings.mock_scenario)
            self.broker = MockBroker()
            self._live = False

        # Sub-agents
        self.market_agent = MarketAnalysisAgent(settings, self.market_provider)
        self.strategy_agent = StrategySelectorAgent(settings)
        self.reviewer_agent = StrategyReviewerAgent(settings)
        self.news_agent = NewsAgent(settings, self.news_provider)
        self.confirmation_agent = ConfirmationAgent(settings)
        self.execution_agent = ExecutionAgent(settings, self.broker)
        self.risk_manager = RiskManagerAgent(settings, self.broker)

        # Master override client
        self._override_client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

    # ─────────────────────────────────────────────────────────────────────────
    # Public entry point
    # ─────────────────────────────────────────────────────────────────────────

    async def run_pipeline(self, instrument: str, timeframe: str) -> PipelineContext:
        run_id = str(uuid.uuid4())[:8]
        ctx = PipelineContext(
            instrument=instrument,
            timeframe=timeframe,
            run_id=run_id,
        )

        with TradingDashboard(self.console) as dashboard:
            self.dashboard = dashboard
            mode = "LIVE MT5" if self._live else f"MOCK ({self.settings.mock_scenario})"
            dashboard.add_log(f"Pipeline started — {instrument} {timeframe} [{mode}] (run {run_id})", "info")

            # Connect to MT5 if live
            if self._live:
                dashboard.add_log("Connecting to MT5 terminal...", "info")
                try:
                    await self.broker.connect()
                    dashboard.add_log("MT5 connected successfully", "success")
                except Exception as exc:
                    dashboard.add_log(f"MT5 connection failed: {exc}", "error")
                    ctx.pipeline_status = "aborted"
                    ctx.error_message = str(exc)
                    return ctx

            try:
                # Stage 1: Market Analysis
                ctx = await self._stage_market_analysis(ctx)
                if ctx.pipeline_status == "aborted":
                    return ctx

                # Stage 2: Strategy Selection + Review (retry loop)
                ctx = await self._stage_strategy_loop(ctx)
                if ctx.pipeline_status == "aborted":
                    return ctx

                # Stage 3: News (parallel with anything else, here standalone)
                ctx = await self._stage_news(ctx)

                # Stage 4: Confirmation
                ctx = await self._stage_confirmation(ctx)
                if ctx.confirmation and ctx.confirmation.decision == "NO_GO":
                    ctx.pipeline_status = "no_go"
                    dashboard.add_log(
                        f"NO-GO: {ctx.confirmation.reasoning[:80]}", "warning"
                    )
                    dashboard.update(ctx)
                    return ctx

                # Stage 5: Execution
                ctx = await self._stage_execution(ctx)
                if ctx.pipeline_status == "aborted":
                    return ctx

                # Stage 6: Risk Management loop
                ctx = await self._stage_risk_management(ctx)

            except Exception as exc:
                self.logger.exception(f"Pipeline fatal error: {exc}")
                ctx.pipeline_status = "aborted"
                ctx.error_message = str(exc)
                dashboard.add_log(f"FATAL: {exc}", "error")
                dashboard.update(ctx)
            finally:
                if self._live:
                    await self.broker.disconnect()
                    dashboard.add_log("MT5 disconnected", "info")

            if ctx.pipeline_status not in ("aborted", "no_go"):
                ctx.pipeline_status = "completed"
                dashboard.add_log("Pipeline completed successfully.", "success")
            dashboard.update(ctx)
            return ctx

    # ─────────────────────────────────────────────────────────────────────────
    # Stage implementations
    # ─────────────────────────────────────────────────────────────────────────

    async def _stage_market_analysis(self, ctx: PipelineContext) -> PipelineContext:
        self._set_stage(ctx, "MarketAnalysis", "running")
        self.dashboard.update(ctx)
        self.dashboard.add_log(
            f"[MarketAnalysis] Analyzing {ctx.instrument} {ctx.timeframe}...", "info"
        )

        prompt = self.market_agent.build_prompt(ctx.instrument, ctx.timeframe)
        decision = await self.market_agent.run(prompt)
        ctx.agent_log.append(decision)

        if decision.output:
            ctx.market_state = self._parse_market_state(decision.output, ctx)
            self._set_stage(ctx, "MarketAnalysis", "success")
            trend = ctx.market_state.trend or "unknown"
            conf = ctx.market_state.trend_confidence or 0
            self.dashboard.add_log(
                f"[MarketAnalysis] {trend.upper()} trend (confidence {conf:.0%})", "success"
            )
        else:
            self._set_stage(ctx, "MarketAnalysis", "failed")
            ctx.pipeline_status = "aborted"
            self.dashboard.add_log("[MarketAnalysis] Failed to analyze market", "error")

        self.dashboard.update(ctx)
        return ctx

    async def _stage_strategy_loop(self, ctx: PipelineContext) -> PipelineContext:
        market_json = self._market_summary_json(ctx.market_state)
        rejection_reason: Optional[str] = None

        for attempt in range(1, self.settings.max_strategy_retries + 1):
            ctx.strategy_attempt_count = attempt

            # Strategy Selection
            self._set_stage(ctx, "StrategySelector", "running")
            self.dashboard.update(ctx)
            prompt = self.strategy_agent.build_prompt(
                market_json, rejection_reason=rejection_reason, attempt=attempt
            )
            sel_decision = await self.strategy_agent.run(prompt)
            ctx.agent_log.append(sel_decision)

            if not sel_decision.output or "strategy_type" not in sel_decision.output:
                self._set_stage(ctx, "StrategySelector", "failed")
                self.dashboard.add_log("[StrategySelector] Failed to produce strategy", "error")
                if attempt == self.settings.max_strategy_retries:
                    ctx.pipeline_status = "aborted"
                    return ctx
                continue

            ctx.strategy_proposal = self._parse_strategy_proposal(sel_decision.output)
            self._set_stage(ctx, "StrategySelector", "success")
            self.dashboard.add_log(
                f"[StrategySelector] Proposed: {ctx.strategy_proposal.strategy_type.value} "
                f"{ctx.strategy_proposal.direction.value} (conf {ctx.strategy_proposal.confidence:.0%})",
                "info",
            )
            self.dashboard.update(ctx)

            # Strategy Review
            self._set_stage(ctx, "StrategyReviewer", "running")
            self.dashboard.update(ctx)
            review_prompt = self.reviewer_agent.build_prompt(
                json.dumps(sel_decision.output, indent=2),
                market_json,
            )
            rev_decision = await self.reviewer_agent.run(review_prompt)
            ctx.agent_log.append(rev_decision)

            ctx.review_decision = self._parse_review_decision(rev_decision.output)

            if ctx.review_decision.approved:
                self._set_stage(ctx, "StrategyReviewer", "success")
                self.dashboard.add_log(
                    f"[StrategyReviewer] APPROVED — win rate {ctx.review_decision.historical_win_rate:.0%}",
                    "success",
                )
                self.dashboard.update(ctx)
                return ctx

            rejection_reason = ctx.review_decision.rejection_reason or "Strategy did not meet criteria"
            self._set_stage(ctx, "StrategyReviewer", "failed")
            self.dashboard.add_log(
                f"[StrategyReviewer] REJECTED (attempt {attempt}): {rejection_reason}", "warning"
            )
            self.dashboard.update(ctx)

            if attempt == self.settings.max_strategy_retries:
                self.dashboard.add_log("[MasterAgent] Max retries — invoking override...", "warning")
                ctx = await self._master_override(ctx)
                return ctx

        return ctx

    async def _stage_news(self, ctx: PipelineContext) -> PipelineContext:
        self._set_stage(ctx, "NewsAgent", "running")
        self.dashboard.update(ctx)
        direction = ctx.strategy_proposal.direction.value if ctx.strategy_proposal else "buy"
        prompt = self.news_agent.build_prompt(ctx.instrument, direction)
        news_decision = await self.news_agent.run(prompt)
        ctx.agent_log.append(news_decision)

        ctx.news_assessment = self._parse_news_assessment(news_decision.output)
        self._set_stage(ctx, "NewsAgent", "success")
        self.dashboard.add_log(
            f"[NewsAgent] {ctx.news_assessment.trade_recommendation.upper()} — "
            f"sentiment {ctx.news_assessment.sentiment} ({ctx.news_assessment.sentiment_score:+.2f})",
            "info",
        )
        self.dashboard.update(ctx)
        return ctx

    async def _stage_confirmation(self, ctx: PipelineContext) -> PipelineContext:
        self._set_stage(ctx, "ConfirmationAgent", "running")
        self.dashboard.update(ctx)

        direction = ctx.strategy_proposal.direction.value if ctx.strategy_proposal else "buy"
        prompt = self.confirmation_agent.build_prompt(
            review_json=json.dumps(ctx.review_decision.model_dump() if ctx.review_decision else {}, indent=2),
            news_json=json.dumps(ctx.news_assessment.model_dump() if ctx.news_assessment else {}, indent=2),
            market_summary=self._market_summary_json(ctx.market_state),
            direction=direction,
            instrument=ctx.instrument,
        )
        conf_decision = await self.confirmation_agent.run(prompt)
        ctx.agent_log.append(conf_decision)

        ctx.confirmation = self._parse_confirmation(conf_decision.output)
        status = "success" if ctx.confirmation.decision == "GO" else "failed"
        self._set_stage(ctx, "ConfirmationAgent", status)
        self.dashboard.add_log(
            f"[ConfirmationAgent] {ctx.confirmation.decision} — risk {ctx.confirmation.risk_score:.2f}",
            "success" if ctx.confirmation.decision == "GO" else "warning",
        )
        self.dashboard.update(ctx)
        return ctx

    async def _stage_execution(self, ctx: PipelineContext) -> PipelineContext:
        self._set_stage(ctx, "ExecutionAgent", "running")
        self.dashboard.update(ctx)

        sp = ctx.strategy_proposal
        prompt = self.execution_agent.build_prompt(
            instrument=ctx.instrument,
            direction=sp.direction.value,
            strategy_name=sp.strategy_type.value,
        )
        exec_decision = await self.execution_agent.run(prompt)
        ctx.agent_log.append(exec_decision)

        out = exec_decision.output
        if out.get("status") == "placed" and out.get("trade_id"):
            ctx.live_trade = LiveTrade(
                trade_id=out["trade_id"],
                signal=TradeSignal(
                    instrument=ctx.instrument,
                    direction=sp.direction,
                    entry_price=out["entry_price"],
                    stop_loss=out["stop_loss"],
                    take_profit=out["take_profit"],
                    strategy_name=sp.strategy_type.value,
                    rationale=sp.rationale,
                ),
                actual_entry_price=out["entry_price"],
                current_price=out["entry_price"],
                current_sl=out["stop_loss"],
                current_tp=out["take_profit"],
                lot_size=out.get("lot_size", 0.1),
            )
            self._set_stage(ctx, "ExecutionAgent", "success")
            self.dashboard.add_log(
                f"[ExecutionAgent] Trade placed: {out['trade_id']} "
                f"{out['direction'].upper()} @ {out['entry_price']}  "
                f"SL:{out['stop_loss']}  TP:{out['take_profit']}",
                "success",
            )
        else:
            # Retry once
            self.dashboard.add_log("[ExecutionAgent] First attempt failed, retrying...", "warning")
            exec_decision2 = await self.execution_agent.run(prompt)
            ctx.agent_log.append(exec_decision2)
            out2 = exec_decision2.output
            if out2.get("status") == "placed" and out2.get("trade_id"):
                ctx.live_trade = LiveTrade(
                    trade_id=out2["trade_id"],
                    signal=TradeSignal(
                        instrument=ctx.instrument,
                        direction=sp.direction,
                        entry_price=out2["entry_price"],
                        stop_loss=out2["stop_loss"],
                        take_profit=out2["take_profit"],
                        strategy_name=sp.strategy_type.value,
                        rationale=sp.rationale,
                    ),
                    actual_entry_price=out2["entry_price"],
                    current_price=out2["entry_price"],
                    current_sl=out2["stop_loss"],
                    current_tp=out2["take_profit"],
                    lot_size=out2.get("lot_size", 0.1),
                )
                self._set_stage(ctx, "ExecutionAgent", "success")
                self.dashboard.add_log(
                    f"[ExecutionAgent] Trade placed on retry: {out2['trade_id']}", "success"
                )
            else:
                self._set_stage(ctx, "ExecutionAgent", "failed")
                ctx.pipeline_status = "aborted"
                self.dashboard.add_log("[ExecutionAgent] Failed to place trade", "error")

        self.dashboard.update(ctx)
        return ctx

    async def _stage_risk_management(self, ctx: PipelineContext) -> PipelineContext:
        if not ctx.live_trade:
            return ctx

        self._set_stage(ctx, "RiskManager", "running")
        self.dashboard.update(ctx)
        self.dashboard.add_log(
            f"[RiskManager] Monitoring {ctx.live_trade.trade_id}...", "info"
        )

        trade = ctx.live_trade
        poll = self.settings.poll_interval_seconds
        max_ticks = 200  # safety cap

        for tick_num in range(max_ticks):
            snapshot = {
                "trade_id": trade.trade_id,
                "instrument": ctx.instrument,
                "direction": trade.signal.direction.value,
                "entry_price": trade.actual_entry_price,
                "current_price": trade.current_price,
                "current_sl": trade.current_sl,
                "current_tp": trade.current_tp,
                "breakeven_activated": trade.breakeven_activated,
                "trailing_active": trade.trailing_active,
                "pnl_pips": trade.pnl_pips,
                "open_duration_minutes": int(
                    (datetime.utcnow() - trade.open_time).total_seconds() / 60
                ),
            }

            try:
                rm_decision = await self.risk_manager.run(
                    self.risk_manager.build_prompt(snapshot)
                )
                ctx.agent_log.append(rm_decision)
                out = rm_decision.output

                # Update trade state from agent output
                if "current_price" in out:
                    trade.current_price = float(out["current_price"])
                if "current_sl" in out:
                    trade.current_sl = float(out["current_sl"])
                if "current_pnl_pips" in out:
                    trade.pnl_pips = float(out["current_pnl_pips"])
                if "breakeven_activated" in out:
                    trade.breakeven_activated = bool(out["breakeven_activated"])
                if "trailing_active" in out:
                    trade.trailing_active = bool(out["trailing_active"])

                action = out.get("action", "no_action")
                if action in ("modify_sl", "close_trade") or action != "no_action":
                    self.dashboard.add_log(
                        f"[RiskManager] tick={tick_num + 1} action={action} "
                        f"pnl={trade.pnl_pips:+.1f}pip sl={trade.current_sl:.5f}",
                        "info",
                    )

                if out.get("trade_status") in ("closed", "closed_tp", "closed_sl", "closed_manual"):
                    close_reason = out.get("close_reason", "condition met")
                    trade.status = TradeStatus.CLOSED_TP if "tp" in close_reason else (
                        TradeStatus.CLOSED_SL if "sl" in close_reason else TradeStatus.CLOSED_MANUAL
                    )
                    trade.close_time = datetime.utcnow()
                    trade.close_reason = close_reason
                    self._set_stage(ctx, "RiskManager", "success")
                    self.dashboard.add_log(
                        f"[RiskManager] Trade CLOSED — {close_reason} | "
                        f"Final PnL: {trade.pnl_pips:+.1f} pips",
                        "success",
                    )
                    ctx.live_trade = trade
                    self.dashboard.tick(ctx)
                    return ctx

            except Exception as exc:
                # Safety fallback: pure-Python rule check
                self.logger.error(f"RiskManager error on tick {tick_num}: {exc}")
                if trade.pnl_pips <= -10.0:
                    trade.status = TradeStatus.CLOSED_SL
                    trade.close_reason = "safety_fallback_sl"
                    break
                if trade.pnl_pips >= 20.0:
                    trade.status = TradeStatus.CLOSED_TP
                    trade.close_reason = "safety_fallback_tp"
                    break

            ctx.live_trade = trade
            self.dashboard.tick(ctx)
            await asyncio.sleep(poll)

        self._set_stage(ctx, "RiskManager", "success")
        ctx.live_trade = trade
        self.dashboard.update(ctx)
        return ctx

    # ─────────────────────────────────────────────────────────────────────────
    # Master override (when all strategy retries exhausted)
    # ─────────────────────────────────────────────────────────────────────────

    async def _master_override(self, ctx: PipelineContext) -> PipelineContext:
        prompt = (
            f"All {self.settings.max_strategy_retries} strategy attempts have been rejected.\n\n"
            f"Market State Summary:\n{self._market_summary_json(ctx.market_state)}\n\n"
            f"Last Strategy: {json.dumps(ctx.strategy_proposal.model_dump() if ctx.strategy_proposal else {}, indent=2)}\n"
            f"Last Review: {json.dumps(ctx.review_decision.model_dump() if ctx.review_decision else {}, indent=2)}\n\n"
            f"Decide: ABORT (market genuinely untradeable) or OVERRIDE (force a viable strategy).\n"
            f"Respond as JSON: {{\"action\": \"ABORT\" | \"OVERRIDE\", \"reasoning\": \"...\"}}"
        )
        try:
            response = await self._override_client.messages.create(
                model=self.settings.model,
                max_tokens=1024,
                system="You are the Master Trading System. Make a decisive override decision.",
                messages=[{"role": "user", "content": prompt}],
            )
            text = "".join(b.text for b in response.content if hasattr(b, "text"))
            from agents import extract_json_from_text
            decision = extract_json_from_text(text)
            if decision.get("action") == "ABORT":
                ctx.pipeline_status = "aborted"
                self.dashboard.add_log(
                    f"[MasterAgent] OVERRIDE → ABORT: {decision.get('reasoning', '')[:80]}", "error"
                )
            else:
                # Force approval of last strategy
                if ctx.review_decision:
                    ctx.review_decision.approved = True
                    ctx.review_decision.review_notes += " [MASTER OVERRIDE]"
                self.dashboard.add_log(
                    f"[MasterAgent] OVERRIDE → FORCE strategy: {decision.get('reasoning', '')[:80]}",
                    "warning",
                )
                self._set_stage(ctx, "StrategyReviewer", "success")
        except Exception as exc:
            self.logger.error(f"Override call failed: {exc}")
            ctx.pipeline_status = "aborted"
        return ctx

    # ─────────────────────────────────────────────────────────────────────────
    # Parsing helpers
    # ─────────────────────────────────────────────────────────────────────────

    def _parse_market_state(self, output: dict, ctx: PipelineContext) -> MarketState:
        from datetime import datetime as dt
        ind_data = output.get("indicators", {})
        indicators = TechnicalIndicators(
            ema_fast=float(ind_data.get("ema_fast", 0)),
            ema_slow=float(ind_data.get("ema_slow", 0)),
            ema_200=float(ind_data.get("ema_200", 0)),
            rsi_14=float(ind_data.get("rsi_14", 50)),
            macd_line=float(ind_data.get("macd_line", 0)),
            macd_signal=float(ind_data.get("macd_signal", 0)),
            macd_histogram=float(ind_data.get("macd_histogram", 0)),
            atr_14=float(ind_data.get("atr_14", 0)),
        )
        price = float(output.get("current_price", 0))
        pip_size_val = __import__("utils.pip_calculator", fromlist=["get_pip_size"]).get_pip_size(ctx.instrument)
        trend_str = output.get("trend", "sideways")
        try:
            trend = Trend(trend_str)
        except ValueError:
            trend = Trend.SIDEWAYS
        return MarketState(
            instrument=ctx.instrument,
            timeframe=ctx.timeframe,
            current_price=price,
            bid=round(price - 0.75 * pip_size_val, 5),
            ask=round(price + 0.75 * pip_size_val, 5),
            spread_pips=1.5,
            candles=[],
            indicators=indicators,
            trend=trend,
            trend_confidence=float(output.get("confidence", 0.5)),
            volatility_context=output.get("volatility_context", "normal"),
        )

    def _parse_strategy_proposal(self, output: dict) -> StrategyProposal:
        from models.agent_output import StrategyType
        try:
            st = StrategyType(output.get("strategy_type", "trend_following"))
        except ValueError:
            st = StrategyType.TREND_FOLLOWING
        try:
            direction = TradeDirection(output.get("direction", "buy"))
        except ValueError:
            direction = TradeDirection.BUY
        return StrategyProposal(
            strategy_type=st,
            direction=direction,
            rationale=output.get("rationale", ""),
            confidence=float(output.get("confidence", 0.5)),
            supporting_indicators=output.get("supporting_indicators", []),
            risk_level=output.get("risk_level", "medium"),
        )

    def _parse_review_decision(self, output: dict) -> ReviewDecision:
        return ReviewDecision(
            approved=bool(output.get("approved", False)),
            review_notes=output.get("review_notes", ""),
            historical_win_rate=float(output.get("historical_win_rate", 0.5)),
            suggested_improvements=output.get("suggested_improvements"),
            rejection_reason=output.get("rejection_reason"),
        )

    def _parse_news_assessment(self, output: dict) -> NewsAssessment:
        return NewsAssessment(
            sentiment=output.get("sentiment", "neutral"),
            sentiment_score=float(output.get("sentiment_score", 0.0)),
            high_impact_events=output.get("high_impact_events", []),
            news_summary=output.get("news_summary", ""),
            trade_recommendation=output.get("trade_recommendation", "proceed"),
            sentiment_conflict=bool(output.get("sentiment_conflict", False)),
        )

    def _parse_confirmation(self, output: dict) -> ConfirmationDecision:
        return ConfirmationDecision(
            decision=output.get("decision", "NO_GO"),
            reasoning=output.get("reasoning", ""),
            risk_score=float(output.get("risk_score", 0.5)),
            conditions=output.get("conditions", []),
        )

    def _market_summary_json(self, market_state) -> str:
        if not market_state:
            return "{}"
        ms = market_state
        ind = ms.indicators
        summary = {
            "instrument": ms.instrument,
            "timeframe": ms.timeframe,
            "current_price": ms.current_price,
            "trend": str(ms.trend.value if ms.trend else "unknown"),
            "trend_confidence": ms.trend_confidence,
            "volatility_context": ms.volatility_context,
            "indicators": {
                "ema_fast": ind.ema_fast,
                "ema_slow": ind.ema_slow,
                "ema_200": ind.ema_200,
                "rsi_14": ind.rsi_14,
                "macd_line": ind.macd_line,
                "macd_signal": ind.macd_signal,
                "macd_histogram": ind.macd_histogram,
                "atr_14": ind.atr_14,
            },
        }
        return json.dumps(summary, indent=2)

    def _set_stage(self, ctx: PipelineContext, stage: str, status: str) -> None:
        ctx.stage_statuses[stage] = status
