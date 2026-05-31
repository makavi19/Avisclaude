import json
from typing import Any

from agents import BaseAgent
from tools.market_data import MARKET_DATA_TOOLS, compute_indicators, get_historical_performance
from tools.news_tools import MockNewsProvider

_SYSTEM_PROMPT = """
You are the Market Analysis Agent for a professional algorithmic trading system.

Your job is to:
1. Fetch OHLCV price data using get_ohlcv_data
2. Get the current price using get_current_price
3. Compute all technical indicators using compute_technical_indicators
4. Determine the market trend and confidence level

TREND DETERMINATION RULES:
- BULLISH: price > EMA_200 AND EMA_fast > EMA_slow AND RSI > 50 AND MACD_histogram > 0
  Count how many of these 4 conditions are true → confidence = count/4
- BEARISH: price < EMA_200 AND EMA_fast < EMA_slow AND RSI < 50 AND MACD_histogram < 0
  Count how many of these 4 conditions are true → confidence = count/4
- SIDEWAYS: fewer than 3 conditions align for either direction, or RSI between 45–55

VOLATILITY CONTEXT:
- If ATR > 1.5x typical ATR for the pair, label as "high"
- If ATR < 0.5x typical, label as "low"
- Otherwise "normal"
  Typical ATR reference: EURUSD M15 ≈ 0.00080, USDJPY M15 ≈ 0.080, XAUUSD ≈ 1.50

REQUIRED: Always call tools first — never guess prices or indicators.

Respond ONLY with a JSON object in this exact format:
{
  "trend": "bullish" | "bearish" | "sideways",
  "confidence": 0.0-1.0,
  "current_price": <float>,
  "indicators": {
    "ema_fast": <float>, "ema_slow": <float>, "ema_200": <float>,
    "rsi_14": <float>, "macd_line": <float>, "macd_signal": <float>,
    "macd_histogram": <float>, "atr_14": <float>
  },
  "conditions_met": ["list of conditions that fired"],
  "volatility_context": "normal" | "high" | "low",
  "reasoning": "concise explanation"
}
""".strip()


class MarketAnalysisAgent(BaseAgent):
    def __init__(self, settings, market_provider):
        super().__init__(
            name="MarketAnalysis",
            system_prompt=_SYSTEM_PROMPT,
            tools=MARKET_DATA_TOOLS,
            model=settings.model,
            api_key=settings.anthropic_api_key,
        )
        self.market_provider = market_provider
        self.settings = settings

    async def _execute_tool(self, tool_name: str, tool_input: dict[str, Any]) -> Any:
        if tool_name == "get_ohlcv_data":
            return await self.market_provider.get_ohlcv(
                instrument=tool_input["instrument"],
                timeframe=tool_input["timeframe"],
                count=tool_input.get("count", 200),
            )
        if tool_name == "get_current_price":
            return await self.market_provider.get_current_price(
                instrument=tool_input["instrument"]
            )
        if tool_name == "compute_technical_indicators":
            return compute_indicators(
                closes=tool_input["closes"],
                highs=tool_input["highs"],
                lows=tool_input["lows"],
            )
        if tool_name == "get_historical_performance":
            return get_historical_performance(
                strategy_type=tool_input["strategy_type"],
                instrument=tool_input["instrument"],
            )
        raise ValueError(f"Unknown tool: {tool_name}")

    def build_prompt(self, instrument: str, timeframe: str) -> str:
        return (
            f"Analyze {instrument} on the {timeframe} timeframe. "
            f"Fetch the last 200 candles, compute all technical indicators, "
            f"and determine the current market trend with a confidence score."
        )
