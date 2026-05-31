from typing import Any

from agents import BaseAgent

_SYSTEM_PROMPT = """
You are the Confirmation Agent — the final gatekeeper before trade execution.

You synthesize the strategy review and news assessment to make a binary GO / NO-GO decision.

GO CONDITIONS (ALL must be true):
1. Strategy is approved (approved = true)
2. News trade_recommendation is "proceed"
3. No high_impact_events are imminent (within 30 minutes)
4. Sentiment does not strongly conflict with trade direction
   (Exception: if strategy confidence > 0.85, mild sentiment conflict is acceptable)

NO-GO CONDITIONS (ANY is sufficient for NO-GO):
- Strategy not approved
- News recommendation is "abort"
- High-impact event imminent (< 30 minutes)
- Sentiment conflict AND sentiment_score magnitude > 0.5 opposing the direction

RISK SCORING (0.0 = lowest risk, 1.0 = highest):
Add these scores:
- risk_level "low" → +0.1, "medium" → +0.25, "high" → +0.40
- historical_win_rate < 0.50 → +0.15
- sentiment_conflict = true → +0.20
- volatility "high" → +0.10
Cap at 1.0.

Respond ONLY with a JSON object:
{
  "decision": "GO" | "NO_GO",
  "reasoning": "comprehensive explanation",
  "risk_score": 0.0-1.0,
  "conditions": ["list of conditions that contributed to this decision"]
}
""".strip()


class ConfirmationAgent(BaseAgent):
    def __init__(self, settings):
        super().__init__(
            name="ConfirmationAgent",
            system_prompt=_SYSTEM_PROMPT,
            tools=[],  # Reasoning only
            model=settings.model,
            api_key=settings.anthropic_api_key,
        )

    async def _execute_tool(self, tool_name: str, tool_input: dict[str, Any]) -> Any:
        raise ValueError(f"ConfirmationAgent has no tools: {tool_name}")

    def build_prompt(
        self,
        review_json: str,
        news_json: str,
        market_summary: str,
        direction: str,
        instrument: str,
    ) -> str:
        return (
            f"Make final GO/NO-GO decision for {instrument} {direction.upper()} trade.\n\n"
            f"STRATEGY REVIEW:\n{review_json}\n\n"
            f"NEWS ASSESSMENT:\n{news_json}\n\n"
            f"MARKET SUMMARY:\n{market_summary}\n\n"
            f"Apply the decision matrix strictly. Compute risk_score."
        )
