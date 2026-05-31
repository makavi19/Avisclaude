import json
from typing import Any

from agents import BaseAgent
from models.agent_output import StrategyProposal, StrategyType
from models.trade import TradeDirection

_SYSTEM_PROMPT = """
You are the Strategy Selector Agent for an algorithmic trading system.

Given market analysis data, select the optimal trading strategy.

STRATEGY SELECTION RULES:
1. TREND_FOLLOWING (preferred when conditions are clear):
   - Use when: trend is BULLISH or BEARISH with confidence >= 0.60
   - Direction: follow the trend (BUY if bullish, SELL if bearish)
   - Risk: medium

2. RANGE:
   - Use when: trend is SIDEWAYS, RSI between 40–60, ATR below normal
   - Direction: BUY near support (price near lower Bollinger/EMA), SELL near resistance
   - Risk: low

3. BREAKOUT:
   - Use when: ATR is elevated (high volatility), price is at or just breaking key EMA levels
   - Direction: follow the breakout direction
   - Risk: high

4. REVERSAL:
   - Use ONLY when: RSI < 25 (oversold → BUY) or RSI > 75 (overbought → SELL)
   - Risk: high

SELECTION PRIORITY: TREND_FOLLOWING > RANGE > REVERSAL > BREAKOUT

If a previous attempt was rejected, pick a DIFFERENT strategy type or direction.

Respond ONLY with a JSON object:
{
  "strategy_type": "trend_following" | "range" | "breakout" | "reversal",
  "direction": "buy" | "sell",
  "rationale": "clear explanation referencing indicator values",
  "confidence": 0.0-1.0,
  "supporting_indicators": ["indicator1", "indicator2"],
  "risk_level": "low" | "medium" | "high"
}
""".strip()


class StrategySelectorAgent(BaseAgent):
    def __init__(self, settings):
        super().__init__(
            name="StrategySelector",
            system_prompt=_SYSTEM_PROMPT,
            tools=[],  # No tool calls — works from context only
            model=settings.model,
            api_key=settings.anthropic_api_key,
        )

    async def _execute_tool(self, tool_name: str, tool_input: dict[str, Any]) -> Any:
        raise ValueError(f"StrategySelector has no tools: {tool_name}")

    def build_prompt(
        self,
        market_state_json: str,
        rejection_reason: str | None = None,
        attempt: int = 1,
    ) -> str:
        base = (
            f"Select the best trading strategy based on this market analysis:\n\n"
            f"{market_state_json}"
        )
        if rejection_reason:
            base += (
                f"\n\nPREVIOUS ATTEMPT #{attempt - 1} WAS REJECTED because: {rejection_reason}\n"
                f"You MUST select a different strategy type or direction."
            )
        return base
