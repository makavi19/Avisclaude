from typing import Any

from agents import BaseAgent
from tools.market_data import MARKET_DATA_TOOLS, get_historical_performance

_SYSTEM_PROMPT = """
You are the Strategy Reviewer Agent. Your role is to critically evaluate proposed trading strategies.

REVIEW CRITERIA:
1. VALIDITY: Does the strategy align with current market conditions?
2. HISTORICAL PERFORMANCE: Call get_historical_performance to check win rate.
3. DIRECTIONAL ALIGNMENT: Does the proposed direction agree with key indicators?
4. RISK ASSESSMENT: Is the risk level acceptable?

REJECTION CONDITIONS (reject if ANY is true):
- Strategy confidence < 0.50
- TREND_FOLLOWING with direction opposing EMA_200 (e.g., BUY but price < EMA_200)
- REVERSAL selected when RSI is NOT in extreme territory (< 25 for BUY or > 75 for SELL)
- BREAKOUT without elevated ATR (volatility_context must be "high" for breakout)
- Historical win rate < 0.40 from get_historical_performance

APPROVAL CONDITIONS:
- Strategy confidence >= 0.50
- Directional alignment with majority of indicators
- Historical win rate >= 0.40
- Risk level appropriate for conditions

Respond ONLY with a JSON object:
{
  "approved": true | false,
  "review_notes": "detailed assessment",
  "historical_win_rate": 0.0-1.0,
  "suggested_improvements": "string or null",
  "rejection_reason": "specific reason or null"
}
""".strip()

_REVIEW_TOOLS = [t for t in MARKET_DATA_TOOLS if t["name"] == "get_historical_performance"]


class StrategyReviewerAgent(BaseAgent):
    def __init__(self, settings):
        super().__init__(
            name="StrategyReviewer",
            system_prompt=_SYSTEM_PROMPT,
            tools=_REVIEW_TOOLS,
            model=settings.model,
            api_key=settings.anthropic_api_key,
        )

    async def _execute_tool(self, tool_name: str, tool_input: dict[str, Any]) -> Any:
        if tool_name == "get_historical_performance":
            return get_historical_performance(
                strategy_type=tool_input["strategy_type"],
                instrument=tool_input["instrument"],
            )
        raise ValueError(f"Unknown tool: {tool_name}")

    def build_prompt(self, strategy_json: str, market_state_json: str) -> str:
        return (
            f"Review this trading strategy proposal:\n\n"
            f"STRATEGY: {strategy_json}\n\n"
            f"MARKET STATE: {market_state_json}\n\n"
            f"Call get_historical_performance to check the win rate, then give your verdict."
        )
