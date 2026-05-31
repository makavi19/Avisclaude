from datetime import datetime, timedelta
import random

NEWS_TOOLS = [
    {
        "name": "get_economic_calendar",
        "description": (
            "Get upcoming and recent high-impact economic events for an instrument's currencies. "
            "Returns events within the specified time window."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "instrument": {"type": "string"},
                "hours_ahead": {"type": "integer", "default": 24},
                "hours_behind": {"type": "integer", "default": 4},
            },
            "required": ["instrument"],
        },
    },
    {
        "name": "get_market_news",
        "description": "Fetch recent news headlines and summaries for a financial instrument.",
        "input_schema": {
            "type": "object",
            "properties": {
                "instrument": {"type": "string"},
                "count": {"type": "integer", "default": 10},
            },
            "required": ["instrument"],
        },
    },
    {
        "name": "analyze_news_sentiment",
        "description": (
            "Compute sentiment score for news headlines. "
            "Returns score from -1.0 (very bearish) to +1.0 (very bullish)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "headlines": {"type": "array", "items": {"type": "string"}},
                "instrument": {"type": "string"},
            },
            "required": ["headlines", "instrument"],
        },
    },
]

_BULLISH_KEYWORDS = [
    "surges", "rises", "gains", "strong", "bullish", "growth", "beats expectations",
    "hawkish", "rate hike", "strong jobs", "robust", "record high", "upbeat",
]
_BEARISH_KEYWORDS = [
    "falls", "drops", "slumps", "weak", "bearish", "recession", "misses",
    "dovish", "rate cut", "job losses", "disappoints", "record low", "concern",
]

_NEWS_FIXTURES: dict[str, list[str]] = {
    "bullish": [
        "EUR strengthens as ECB signals hawkish stance on inflation",
        "US dollar weakens on softer-than-expected retail sales data",
        "Eurozone GDP growth beats expectations at 0.4% quarterly",
        "Risk appetite improves as global equities surge",
        "EUR/USD breaks above key resistance amid dollar weakness",
    ],
    "bearish": [
        "EUR falls as Eurozone manufacturing PMI hits 3-year low",
        "Strong US non-farm payrolls boost dollar demand",
        "ECB signals potential rate cuts amid cooling inflation",
        "Geopolitical tensions weigh on risk sentiment",
        "EUR/USD breaks below key support level",
    ],
    "sideways": [
        "Mixed US data leaves traders uncertain on Fed path",
        "EUR/USD consolidates in narrow range ahead of key events",
        "Markets await clarity on central bank policy direction",
        "Low volatility as summer trading conditions persist",
        "Range-bound trading expected before next catalyst",
    ],
    "news_abort": [
        "BREAKING: Federal Reserve emergency meeting scheduled",
        "FOMC rate decision due in 15 minutes — markets on edge",
        "US CPI data release imminent — high volatility expected",
        "NFP report due shortly — analysts forecast 200K jobs added",
        "Major risk event approaching — traders reduce exposure",
    ],
}

_CALENDAR_FIXTURES: dict[str, list[dict]] = {
    "normal": [
        {
            "event": "German Industrial Production",
            "currency": "EUR",
            "impact": "medium",
            "time_offset_hours": 6,
        },
        {
            "event": "US Initial Jobless Claims",
            "currency": "USD",
            "impact": "medium",
            "time_offset_hours": 8,
        },
    ],
    "news_abort": [
        {
            "event": "FOMC Rate Decision",
            "currency": "USD",
            "impact": "high",
            "time_offset_hours": 0.25,  # 15 minutes ahead
        },
        {
            "event": "US Non-Farm Payrolls",
            "currency": "USD",
            "impact": "high",
            "time_offset_hours": 0.1,  # 6 minutes ahead
        },
    ],
}


def _get_calendar_type(scenario: str) -> str:
    return "news_abort" if scenario == "news_abort" else "normal"


class MockNewsProvider:
    def __init__(self, scenario: str = "bullish"):
        self.scenario = scenario

    async def get_economic_calendar(
        self, instrument: str, hours_ahead: int = 24, hours_behind: int = 4
    ) -> dict:
        cal_type = _get_calendar_type(self.scenario)
        events_raw = _CALENDAR_FIXTURES.get(cal_type, _CALENDAR_FIXTURES["normal"])
        now = datetime.utcnow()
        events = []
        for ev in events_raw:
            event_time = now + timedelta(hours=ev["time_offset_hours"])
            minutes_to_event = (event_time - now).total_seconds() / 60
            if -hours_behind * 60 <= (event_time - now).total_seconds() / 60 <= hours_ahead * 60:
                events.append({
                    "event": ev["event"],
                    "currency": ev["currency"],
                    "impact": ev["impact"],
                    "time": event_time.isoformat(),
                    "minutes_to_event": round(minutes_to_event, 1),
                })
        return {"instrument": instrument, "events": events, "count": len(events)}

    async def get_market_news(self, instrument: str, count: int = 10) -> dict:
        scenario_key = self.scenario if self.scenario in _NEWS_FIXTURES else "sideways"
        headlines = _NEWS_FIXTURES[scenario_key][:count]
        now = datetime.utcnow()
        articles = [
            {
                "headline": h,
                "time": (now - timedelta(minutes=i * 15)).isoformat(),
                "source": ["Reuters", "Bloomberg", "FXStreet", "ForexLive"][i % 4],
            }
            for i, h in enumerate(headlines)
        ]
        return {"instrument": instrument, "articles": articles, "count": len(articles)}

    async def analyze_news_sentiment(self, headlines: list[str], instrument: str) -> dict:
        score = 0.0
        for headline in headlines:
            lower = headline.lower()
            bullish_hits = sum(1 for kw in _BULLISH_KEYWORDS if kw in lower)
            bearish_hits = sum(1 for kw in _BEARISH_KEYWORDS if kw in lower)
            score += (bullish_hits - bearish_hits) * 0.15
        score = max(-1.0, min(1.0, score / max(len(headlines), 1)))
        if score > 0.3:
            sentiment = "positive"
        elif score < -0.3:
            sentiment = "negative"
        else:
            sentiment = "neutral"
        return {
            "sentiment": sentiment,
            "score": round(score, 3),
            "headlines_analyzed": len(headlines),
            "instrument": instrument,
        }
