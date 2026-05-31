from __future__ import annotations

from datetime import datetime
from typing import Optional

from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich import box

from models.agent_output import PipelineContext


_STAGE_ORDER = [
    "MarketAnalysis",
    "StrategySelector",
    "StrategyReviewer",
    "NewsAgent",
    "ConfirmationAgent",
    "ExecutionAgent",
    "RiskManager",
]

_STATUS_ICONS = {
    "pending": "[dim]○[/dim]",
    "running": "[yellow]●[/yellow]",
    "success": "[green]✓[/green]",
    "failed":  "[red]✗[/red]",
    "skipped": "[dim]–[/dim]",
}


class TradingDashboard:
    def __init__(self, console: Console):
        self.console = console
        self._ctx: Optional[PipelineContext] = None
        self._log_lines: list[str] = []
        self._start_time = datetime.utcnow()
        self._live = Live(
            self._render(),
            console=console,
            refresh_per_second=4,
            screen=False,
        )

    def __enter__(self) -> "TradingDashboard":
        self._live.start()
        return self

    def __exit__(self, *args) -> None:
        self._live.stop()

    def update(self, ctx: PipelineContext) -> None:
        self._ctx = ctx
        self._live.update(self._render())

    def tick(self, ctx: PipelineContext) -> None:
        self._ctx = ctx
        self._live.update(self._render())

    def add_log(self, message: str, level: str = "info") -> None:
        color = {"info": "white", "warning": "yellow", "error": "red", "success": "green"}.get(level, "white")
        ts = datetime.utcnow().strftime("%H:%M:%S")
        self._log_lines.append(f"[dim]{ts}[/dim] [{color}]{message}[/{color}]")
        if len(self._log_lines) > 12:
            self._log_lines = self._log_lines[-12:]
        if self._ctx:
            self._live.update(self._render())

    # ── Rendering ────────────────────────────────────────────────────────────

    def _render(self) -> Layout:
        ctx = self._ctx
        layout = Layout()
        layout.split_column(
            Layout(name="header", size=3),
            Layout(name="top", size=14),
            Layout(name="middle", size=8),
            Layout(name="log", size=10),
        )
        layout["top"].split_row(
            Layout(name="pipeline", ratio=1),
            Layout(name="market", ratio=1),
            Layout(name="trade", ratio=1),
        )
        layout["middle"].split_row(
            Layout(name="strategy", ratio=1),
            Layout(name="news", ratio=1),
        )

        layout["header"].update(self._header_panel(ctx))
        layout["pipeline"].update(self._pipeline_panel(ctx))
        layout["market"].update(self._market_panel(ctx))
        layout["trade"].update(self._trade_panel(ctx))
        layout["strategy"].update(self._strategy_panel(ctx))
        layout["news"].update(self._news_panel(ctx))
        layout["log"].update(self._log_panel())
        return layout

    def _header_panel(self, ctx: Optional[PipelineContext]) -> Panel:
        elapsed = (datetime.utcnow() - self._start_time).seconds
        instrument = ctx.instrument if ctx else "—"
        timeframe = ctx.timeframe if ctx else "—"
        run_id = ctx.run_id if ctx else "—"
        status = ctx.pipeline_status if ctx else "initializing"
        status_colors = {
            "running": "yellow", "completed": "green",
            "aborted": "red", "no_go": "yellow", "initializing": "dim",
        }
        color = status_colors.get(status, "white")
        content = (
            f"[bold cyan]MASTER TRADER SYSTEM[/bold cyan]  |  "
            f"[green]{instrument}[/green] {timeframe}  |  "
            f"Run: [dim]{run_id}[/dim]  |  "
            f"Elapsed: {elapsed}s  |  "
            f"Status: [{color}]{status.upper()}[/{color}]"
        )
        return Panel(content, box=box.HORIZONTALS)

    def _pipeline_panel(self, ctx: Optional[PipelineContext]) -> Panel:
        table = Table(box=None, show_header=False, padding=(0, 1))
        table.add_column("icon", width=3)
        table.add_column("name")
        table.add_column("info", style="dim")

        statuses = ctx.stage_statuses if ctx else {}
        for stage in _STAGE_ORDER:
            st = statuses.get(stage, "pending")
            icon = _STATUS_ICONS.get(st, "○")
            info = ""
            if ctx and st == "success":
                # Provide key output snippet
                if stage == "MarketAnalysis" and ctx.market_state:
                    trend = ctx.market_state.trend or "—"
                    conf = ctx.market_state.trend_confidence or 0
                    info = f"{trend} {conf:.0%}"
                elif stage == "StrategySelector" and ctx.strategy_proposal:
                    info = f"{ctx.strategy_proposal.strategy_type.value} {ctx.strategy_proposal.direction.value}"
                elif stage == "StrategyReviewer" and ctx.review_decision:
                    info = "APPROVED" if ctx.review_decision.approved else "REJECTED"
                elif stage == "NewsAgent" and ctx.news_assessment:
                    info = ctx.news_assessment.trade_recommendation.upper()
                elif stage == "ConfirmationAgent" and ctx.confirmation:
                    info = ctx.confirmation.decision
                elif stage == "ExecutionAgent" and ctx.live_trade:
                    info = ctx.live_trade.trade_id
                elif stage == "RiskManager" and ctx.live_trade:
                    pnl = ctx.live_trade.pnl_pips
                    color = "green" if pnl >= 0 else "red"
                    info = f"[{color}]{pnl:+.1f} pips[/{color}]"
            table.add_row(icon, stage, info)

        return Panel(table, title="[bold]Pipeline[/bold]", box=box.ROUNDED)

    def _market_panel(self, ctx: Optional[PipelineContext]) -> Panel:
        if not ctx or not ctx.market_state:
            return Panel("[dim]Waiting...[/dim]", title="[bold]Market Analysis[/bold]", box=box.ROUNDED)
        ms = ctx.market_state
        ind = ms.indicators
        trend_color = {"bullish": "green", "bearish": "red", "sideways": "yellow"}.get(
            str(ms.trend or ""), "white"
        )
        lines = [
            f"Trend:   [{trend_color}]{str(ms.trend or '—').upper()}[/{trend_color}]  ({(ms.trend_confidence or 0):.0%})",
            f"Price:   {ms.current_price:.5f}",
            f"Spread:  {ms.spread_pips:.1f} pips",
            f"EMA9:    {ind.ema_fast:.5f}",
            f"EMA21:   {ind.ema_slow:.5f}",
            f"EMA200:  {ind.ema_200:.5f}",
            f"RSI14:   {ind.rsi_14:.1f}",
            f"MACD:    {ind.macd_histogram:+.6f}",
            f"ATR14:   {ind.atr_14:.6f}",
            f"Vol:     {ms.volatility_context.upper()}",
        ]
        return Panel("\n".join(lines), title="[bold]Market Analysis[/bold]", box=box.ROUNDED)

    def _trade_panel(self, ctx: Optional[PipelineContext]) -> Panel:
        if not ctx or not ctx.live_trade:
            return Panel("[dim]No trade yet[/dim]", title="[bold]Active Trade[/bold]", box=box.ROUNDED)
        t = ctx.live_trade
        pnl_color = "green" if t.pnl_pips >= 0 else "red"
        sl_state = (
            "TRAILING" if t.trailing_active
            else "BREAKEVEN" if t.breakeven_activated
            else "INITIAL"
        )
        dir_color = "green" if t.signal.direction.value == "buy" else "red"
        lines = [
            f"ID:       {t.trade_id}",
            f"Dir:      [{dir_color}]{t.signal.direction.value.upper()}[/{dir_color}]",
            f"Entry:    {t.actual_entry_price:.5f}",
            f"SL:       {t.current_sl:.5f}",
            f"TP:       {t.current_tp:.5f}",
            f"Current:  {t.current_price:.5f}",
            f"PnL:      [{pnl_color}]{t.pnl_pips:+.1f} pips[/{pnl_color}]",
            f"SL State: [cyan]{sl_state}[/cyan]",
            f"Status:   {t.status.value.upper()}",
        ]
        return Panel("\n".join(lines), title="[bold]Active Trade[/bold]", box=box.ROUNDED)

    def _strategy_panel(self, ctx: Optional[PipelineContext]) -> Panel:
        if not ctx or not ctx.strategy_proposal:
            return Panel("[dim]Waiting...[/dim]", title="[bold]Strategy[/bold]", box=box.ROUNDED)
        sp = ctx.strategy_proposal
        rv = ctx.review_decision
        dir_color = "green" if sp.direction.value == "buy" else "red"
        approved_text = (
            "[green]APPROVED[/green]" if (rv and rv.approved)
            else "[red]REJECTED[/red]" if rv
            else "[dim]pending[/dim]"
        )
        risk_color = {"low": "green", "medium": "yellow", "high": "red"}.get(sp.risk_level, "white")
        lines = [
            f"Type:     {sp.strategy_type.value.upper()}",
            f"Dir:      [{dir_color}]{sp.direction.value.upper()}[/{dir_color}]",
            f"Conf:     {sp.confidence:.0%}",
            f"Risk:     [{risk_color}]{sp.risk_level.upper()}[/{risk_color}]",
            f"Review:   {approved_text}",
        ]
        if rv:
            wr = rv.historical_win_rate
            lines.append(f"Win Rate: {wr:.0%}")
        return Panel("\n".join(lines), title="[bold]Strategy[/bold]", box=box.ROUNDED)

    def _news_panel(self, ctx: Optional[PipelineContext]) -> Panel:
        if not ctx or not ctx.news_assessment:
            return Panel("[dim]Waiting...[/dim]", title="[bold]News & Sentiment[/bold]", box=box.ROUNDED)
        na = ctx.news_assessment
        sent_color = {"positive": "green", "negative": "red", "neutral": "yellow"}.get(
            na.sentiment, "white"
        )
        rec_color = {"proceed": "green", "wait": "yellow", "abort": "red"}.get(
            na.trade_recommendation, "white"
        )
        events_text = ", ".join(na.high_impact_events[:2]) if na.high_impact_events else "None"
        lines = [
            f"Sentiment: [{sent_color}]{na.sentiment.upper()}[/{sent_color}] ({na.sentiment_score:+.2f})",
            f"Events:    {events_text}",
            f"Rec:       [{rec_color}]{na.trade_recommendation.upper()}[/{rec_color}]",
            f"Conflict:  {'[red]YES[/red]' if na.sentiment_conflict else '[green]NO[/green]'}",
        ]
        if na.news_summary:
            lines.append(f"[dim]{na.news_summary[:60]}...[/dim]")
        return Panel("\n".join(lines), title="[bold]News & Sentiment[/bold]", box=box.ROUNDED)

    def _log_panel(self) -> Panel:
        content = "\n".join(self._log_lines[-10:]) if self._log_lines else "[dim]No events yet[/dim]"
        return Panel(content, title="[bold]Event Log[/bold]", box=box.ROUNDED)
