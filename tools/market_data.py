import numpy as np
from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from typing import Any

from utils.pip_calculator import get_pip_size


# ─── Tool definitions for Anthropic tool_use ─────────────────────────────────

MARKET_DATA_TOOLS = [
    {
        "name": "get_ohlcv_data",
        "description": (
            "Fetch historical OHLCV candlestick data for a given instrument and timeframe. "
            "Returns the last N candles as a list of {timestamp, open, high, low, close, volume}."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "instrument": {"type": "string", "description": "e.g. EURUSD, GBPUSD, US30"},
                "timeframe": {"type": "string", "description": "M1, M5, M15, H1, H4, D1"},
                "count": {"type": "integer", "description": "Number of candles (max 500)", "default": 200},
            },
            "required": ["instrument", "timeframe"],
        },
    },
    {
        "name": "get_current_price",
        "description": "Get the current bid/ask price and spread for an instrument.",
        "input_schema": {
            "type": "object",
            "properties": {
                "instrument": {"type": "string"},
            },
            "required": ["instrument"],
        },
    },
    {
        "name": "compute_technical_indicators",
        "description": (
            "Compute EMA(9), EMA(21), EMA(200), RSI(14), MACD(12,26,9), and ATR(14) "
            "from provided OHLCV arrays."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "closes": {"type": "array", "items": {"type": "number"}},
                "highs": {"type": "array", "items": {"type": "number"}},
                "lows": {"type": "array", "items": {"type": "number"}},
            },
            "required": ["closes", "highs", "lows"],
        },
    },
    {
        "name": "get_historical_performance",
        "description": "Get mock historical win rate for a strategy/instrument combination.",
        "input_schema": {
            "type": "object",
            "properties": {
                "strategy_type": {"type": "string"},
                "instrument": {"type": "string"},
            },
            "required": ["strategy_type", "instrument"],
        },
    },
]


# ─── Indicator computation (pure numpy) ──────────────────────────────────────

def _ema(series: np.ndarray, period: int) -> np.ndarray:
    alpha = 2.0 / (period + 1)
    result = np.empty_like(series)
    result[0] = series[0]
    for i in range(1, len(series)):
        result[i] = series[i] * alpha + result[i - 1] * (1 - alpha)
    return result


def _rsi(closes: np.ndarray, period: int = 14) -> float:
    if len(closes) < period + 1:
        return 50.0
    deltas = np.diff(closes)
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)
    avg_gain = np.mean(gains[:period])
    avg_loss = np.mean(losses[:period])
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def _atr(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, period: int = 14) -> float:
    if len(closes) < 2:
        return 0.0
    tr = np.maximum(
        highs[1:] - lows[1:],
        np.maximum(
            np.abs(highs[1:] - closes[:-1]),
            np.abs(lows[1:] - closes[:-1]),
        ),
    )
    if len(tr) < period:
        return float(np.mean(tr))
    atr = np.mean(tr[:period])
    for i in range(period, len(tr)):
        atr = (atr * (period - 1) + tr[i]) / period
    return float(atr)


def compute_indicators(closes: list[float], highs: list[float], lows: list[float]) -> dict[str, Any]:
    c = np.array(closes, dtype=float)
    h = np.array(highs, dtype=float)
    lo = np.array(lows, dtype=float)

    ema9_arr = _ema(c, 9)
    ema21_arr = _ema(c, 21)
    ema200_arr = _ema(c, 200)

    macd_fast = _ema(c, 12)
    macd_slow = _ema(c, 26)
    macd_line_arr = macd_fast - macd_slow
    signal_arr = _ema(macd_line_arr, 9)

    rsi_val = _rsi(c)
    atr_val = _atr(h, lo, c)

    return {
        "ema_fast": round(float(ema9_arr[-1]), 5),
        "ema_slow": round(float(ema21_arr[-1]), 5),
        "ema_200": round(float(ema200_arr[-1]), 5),
        "rsi_14": round(rsi_val, 2),
        "macd_line": round(float(macd_line_arr[-1]), 6),
        "macd_signal": round(float(signal_arr[-1]), 6),
        "macd_histogram": round(float(macd_line_arr[-1] - signal_arr[-1]), 6),
        "atr_14": round(atr_val, 6),
    }


# ─── Historical performance mock ──────────────────────────────────────────────

_WIN_RATES: dict[tuple[str, str], float] = {
    ("trend_following", "EURUSD"): 0.62,
    ("trend_following", "GBPUSD"): 0.58,
    ("trend_following", "USDJPY"): 0.60,
    ("range", "EURUSD"): 0.55,
    ("range", "GBPUSD"): 0.52,
    ("breakout", "EURUSD"): 0.48,
    ("reversal", "EURUSD"): 0.45,
    ("reversal", "GBPUSD"): 0.43,
}

_DEFAULT_WIN_RATE = 0.50


def get_historical_performance(strategy_type: str, instrument: str) -> dict:
    key = (strategy_type.lower(), instrument.upper().replace("/", ""))
    win_rate = _WIN_RATES.get(key, _DEFAULT_WIN_RATE)
    return {
        "strategy_type": strategy_type,
        "instrument": instrument,
        "win_rate": win_rate,
        "sample_trades": 120,
        "avg_rr": 1.8,
        "notes": f"Based on 120 historical trades for {strategy_type} on {instrument}",
    }


# ─── Market data provider ─────────────────────────────────────────────────────

class MarketDataProvider(ABC):
    @abstractmethod
    async def get_ohlcv(self, instrument: str, timeframe: str, count: int = 200) -> dict:
        ...

    @abstractmethod
    async def get_current_price(self, instrument: str) -> dict:
        ...


_SCENARIO_PARAMS: dict[str, dict] = {
    "bullish": {"trend_pips": 100, "noise_pips": 5, "seed": 42},
    "bearish": {"trend_pips": -100, "noise_pips": 5, "seed": 43},
    "sideways": {"trend_pips": 0, "noise_pips": 8, "seed": 44, "oscillate": True},
    "reversal_oversold": {"trend_pips": -200, "noise_pips": 4, "seed": 45},
    "news_abort": {"trend_pips": 100, "noise_pips": 5, "seed": 46},
}

_BASE_PRICES: dict[str, float] = {
    "EURUSD": 1.08500, "GBPUSD": 1.27200, "USDJPY": 149.500,
    "AUDUSD": 0.65400, "USDCAD": 1.35500, "USDCHF": 0.89200,
    "XAUUSD": 2345.00, "US30": 39500.0, "NAS100": 17800.0,
    "BTCUSD": 68000.0,
}


class MockMarketDataProvider(MarketDataProvider):
    def __init__(self, scenario: str = "bullish"):
        self.scenario = scenario
        self._params = _SCENARIO_PARAMS.get(scenario, _SCENARIO_PARAMS["bullish"])

    def _generate_series(
        self, instrument: str, count: int
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        p = self._params
        base = _BASE_PRICES.get(instrument.upper().replace("/", ""), 1.0)
        pip_size = get_pip_size(instrument)

        rng = np.random.RandomState(p["seed"])
        trend_per_candle = p["trend_pips"] * pip_size / count
        noise_std = p["noise_pips"] * pip_size

        closes = np.zeros(count)
        closes[0] = base
        if p.get("oscillate"):
            t = np.linspace(0, 4 * np.pi, count)
            for i in range(1, count):
                osc = 30 * pip_size * np.sin(t[i])
                closes[i] = base + osc + rng.normal(0, noise_std * 0.3)
        else:
            for i in range(1, count):
                closes[i] = closes[i - 1] + trend_per_candle + rng.normal(0, noise_std)

        candle_range = noise_std * 1.5
        opens = np.concatenate([[closes[0] - trend_per_candle], closes[:-1]])
        highs = np.maximum(closes, opens) + np.abs(rng.normal(0, candle_range / 2, count))
        lows = np.minimum(closes, opens) - np.abs(rng.normal(0, candle_range / 2, count))
        volumes = rng.uniform(1000, 10000, count)

        return opens, highs, lows, closes, volumes

    async def get_ohlcv(self, instrument: str, timeframe: str, count: int = 200) -> dict:
        opens, highs, lows, closes, volumes = self._generate_series(instrument, count)
        now = datetime.utcnow()
        tf_minutes = {"M1": 1, "M5": 5, "M15": 15, "M30": 30, "H1": 60, "H4": 240, "D1": 1440}
        minutes = tf_minutes.get(timeframe.upper(), 15)
        candles = []
        for i in range(count):
            ts = now - timedelta(minutes=minutes * (count - i))
            candles.append({
                "timestamp": ts.isoformat(),
                "open": round(float(opens[i]), 5),
                "high": round(float(highs[i]), 5),
                "low": round(float(lows[i]), 5),
                "close": round(float(closes[i]), 5),
                "volume": round(float(volumes[i]), 2),
            })
        return {"instrument": instrument, "timeframe": timeframe, "candles": candles}

    async def get_current_price(self, instrument: str) -> dict:
        _, _, _, closes, _ = self._generate_series(instrument, 200)
        pip_size = get_pip_size(instrument)
        mid = float(closes[-1])
        spread = 1.5 * pip_size
        return {
            "instrument": instrument,
            "bid": round(mid - spread / 2, 5),
            "ask": round(mid + spread / 2, 5),
            "mid": round(mid, 5),
            "spread_pips": 1.5,
        }
