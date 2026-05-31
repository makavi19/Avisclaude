from typing import Any

from agents import BaseAgent
from tools.news_tools import NEWS_TOOLS, MockNewsProvider

_SYSTEM_PROMPT = """
You are the News and Sentiment Agent for a financial trading system.

Your job is to:
1. Fetch the economic calendar using get_economic_calendar
2. Fetch recent news using get_market_news
3. Analyze sentiment using analyze_news_sentiment
4. Make a trading recommendation

HIGH-IMPACT EVENT RULES (automatic "abort" if event is within 30 minutes):
- Central bank rate decisions (Fed, ECB, BOE, BOJ, RBA)
- Non-Farm Payrolls (NFP)
- CPI / Inflation data
- GDP releases
- Any event with impact = "high" and minutes_to_event < 30

SENTIMENT SCORING:
- If sentiment_score strongly opposes trade direction (score magnitude > 0.5 in wrong direction),
  flag sentiment_conflict = true

TRADE RECOMMENDATION:
- "abort": high-impact event within 30 minutes
- "wait": high-impact event in 30–120 minutes, or strong conflicting sentiment
- "proceed": no imminent high-impact events and sentiment is neutral or supportive

Respond ONLY with a JSON object:
{
  "sentiment": "positive" | "negative" | "neutral",
  "sentiment_score": -1.0 to 1.0,
  "high_impact_events": ["event1 (X min away)", ...],
  "news_summary": "2-sentence summary",
  "trade_recommendation": "proceed" | "wait" | "abort",
  "sentiment_conflict": true | false
}
""".strip()


class NewsAgent(BaseAgent):
    def __init__(self, settings, news_provider: MockNewsProvider):
        super().__init__(
            name="NewsAgent",
            system_prompt=_SYSTEM_PROMPT,
            tools=NEWS_TOOLS,
            model=settings.model,
            api_key=settings.anthropic_api_key,
        )
        self.news_provider = news_provider

    async def _execute_tool(self, tool_name: str, tool_input: dict[str, Any]) -> Any:
        if tool_name == "get_economic_calendar":
            return await self.news_provider.get_economic_calendar(
                instrument=tool_input["instrument"],
                hours_ahead=tool_input.get("hours_ahead", 24),
                hours_behind=tool_input.get("hours_behind", 4),
            )
        if tool_name == "get_market_news":
            return await self.news_provider.get_market_news(
                instrument=tool_input["instrument"],
                count=tool_input.get("count", 10),
            )
        if tool_name == "analyze_news_sentiment":
            return await self.news_provider.analyze_news_sentiment(
                headlines=tool_input["headlines"],
                instrument=tool_input["instrument"],
            )
        raise ValueError(f"Unknown tool: {tool_name}")

    def build_prompt(self, instrument: str, proposed_direction: str) -> str:
        return (
            f"Assess news and sentiment for {instrument}. "
            f"The proposed trade direction is: {proposed_direction.upper()}. "
            f"Check the economic calendar for high-impact events, fetch recent news, "
            f"analyze sentiment, and make a trade recommendation."
        )
