from pydantic import BaseModel, Field
from enum import Enum
from typing import Optional
from datetime import datetime


class Trend(str, Enum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    SIDEWAYS = "sideways"


class OHLCV(BaseModel):
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


class TechnicalIndicators(BaseModel):
    ema_fast: float       # EMA 9
    ema_slow: float       # EMA 21
    ema_200: float        # EMA 200
    rsi_14: float
    macd_line: float
    macd_signal: float
    macd_histogram: float
    atr_14: float


class MarketState(BaseModel):
    instrument: str
    timeframe: str
    current_price: float
    bid: float
    ask: float
    spread_pips: float
    candles: list[OHLCV]
    indicators: TechnicalIndicators
    trend: Optional[Trend] = None
    trend_confidence: Optional[float] = None
    volatility_context: str = "normal"
    analysis_timestamp: datetime = Field(default_factory=datetime.utcnow)
