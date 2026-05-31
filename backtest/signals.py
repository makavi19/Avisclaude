"""
Pure-Python signal generation — mirrors the exact rules in the agent system prompts.
No Claude API calls. Used by the backtesting engine for speed.
"""
from __future__ import annotations

import numpy as np

from tools.market_data import compute_indicators
from utils.pip_calculator import get_pip_size, calculate_sl_price, calculate_tp_price


# ── Trend analysis (mirrors MarketAnalysisAgent) ──────────────────────────────

def analyze_market(
    closes: list[float],
    highs: list[float],
    lows: list[float],
    instrument: str,
) -> dict:
    """Returns trend, confidence, indicators — same logic as MarketAnalysisAgent."""
    if len(closes) < 30:
        return {"trend": "sideways", "confidence": 0.0, "indicators": {}}

    ind = compute_indicators(closes, highs, lows)
    price = closes[-1]

    # Count bullish conditions
    bullish = [
        price > ind["ema_200"],
        ind["ema_fast"] > ind["ema_slow"],
        ind["rsi_14"] > 50,
        ind["macd_histogram"] > 0,
    ]
    # Count bearish conditions
    bearish = [
        price < ind["ema_200"],
        ind["ema_fast"] < ind["ema_slow"],
        ind["rsi_14"] < 50,
        ind["macd_histogram"] < 0,
    ]

    bull_score = sum(bullish)
    bear_score = sum(bearish)

    if bull_score >= 3:
        trend = "bullish"
        confidence = bull_score / 4.0
    elif bear_score >= 3:
        trend = "bearish"
        confidence = bear_score / 4.0
    else:
        trend = "sideways"
        confidence = 1.0 - abs(bull_score - bear_score) / 4.0

    # Volatility
    typical_atr = {"EURUSD": 0.00080, "GBPUSD": 0.00110, "USDJPY": 0.080}.get(
        instrument.upper(), 0.00080
    )
    if ind["atr_14"] > typical_atr * 1.5:
        vol = "high"
    elif ind["atr_14"] < typical_atr * 0.5:
        vol = "low"
    else:
        vol = "normal"

    return {
        "trend": trend,
        "confidence": round(confidence, 2),
        "indicators": ind,
        "volatility_context": vol,
        "current_price": price,
    }


# ── Strategy selection (mirrors StrategySelectorAgent) ────────────────────────

def select_strategy(market: dict) -> dict | None:
    """
    Returns a strategy dict or None if conditions not met.
    Same rules as StrategySelectorAgent system prompt.
    """
    trend = market["trend"]
    conf = market["confidence"]
    ind = market["indicators"]
    rsi = ind.get("rsi_14", 50)
    atr_vol = market.get("volatility_context", "normal")

    # TREND_FOLLOWING
    if trend in ("bullish", "bearish") and conf >= 0.60:
        return {
            "strategy_type": "trend_following",
            "direction": "buy" if trend == "bullish" else "sell",
            "confidence": conf,
            "risk_level": "medium",
        }

    # REVERSAL (extreme RSI)
    if rsi < 25:
        return {
            "strategy_type": "reversal",
            "direction": "buy",
            "confidence": round((25 - rsi) / 25, 2),
            "risk_level": "high",
        }
    if rsi > 75:
        return {
            "strategy_type": "reversal",
            "direction": "sell",
            "confidence": round((rsi - 75) / 25, 2),
            "risk_level": "high",
        }

    # BREAKOUT (high volatility)
    if atr_vol == "high" and conf >= 0.50:
        return {
            "strategy_type": "breakout",
            "direction": "buy" if trend == "bullish" else "sell",
            "confidence": conf,
            "risk_level": "high",
        }

    # RANGE (sideways)
    if trend == "sideways":
        price = market["current_price"]
        ema_mid = (ind["ema_fast"] + ind["ema_slow"]) / 2
        direction = "buy" if price < ema_mid else "sell"
        return {
            "strategy_type": "range",
            "direction": direction,
            "confidence": 0.50,
            "risk_level": "low",
        }

    return None  # No tradeable setup


# ── Strategy review (mirrors StrategyReviewerAgent) ───────────────────────────

_WIN_RATES = {
    ("trend_following", "EURUSD"): 0.62,
    ("trend_following", "GBPUSD"): 0.58,
    ("trend_following", "USDJPY"): 0.60,
    ("range",           "EURUSD"): 0.55,
    ("breakout",        "EURUSD"): 0.48,
    ("reversal",        "EURUSD"): 0.45,
}


def review_strategy(strategy: dict, market: dict, instrument: str) -> bool:
    """Returns True if strategy passes review. Same rules as StrategyReviewerAgent."""
    st = strategy["strategy_type"]
    direction = strategy["direction"]
    confidence = strategy["confidence"]
    ind = market["indicators"]
    price = market["current_price"]
    rsi = ind.get("rsi_14", 50)

    # Reject if confidence too low
    if confidence < 0.50:
        return False

    # TREND_FOLLOWING: direction must agree with EMA 200
    if st == "trend_following":
        if direction == "buy" and price < ind["ema_200"]:
            return False
        if direction == "sell" and price > ind["ema_200"]:
            return False

    # REVERSAL: RSI must be extreme
    if st == "reversal":
        if direction == "buy" and rsi >= 25:
            return False
        if direction == "sell" and rsi <= 75:
            return False

    # BREAKOUT: must have elevated volatility
    if st == "breakout" and market.get("volatility_context") != "high":
        return False

    # Historical win rate check
    key = (st, instrument.upper().replace("/", ""))
    win_rate = _WIN_RATES.get(key, 0.50)
    if win_rate < 0.40:
        return False

    return True


# ── Confirmation (mirrors ConfirmationAgent) ─────────────────────────────────

def confirm_trade(strategy: dict, market: dict, news_sentiment: float = 0.0) -> bool:
    """
    Returns True if trade is confirmed (GO).
    No news high-impact event check in backtest (no live calendar).
    Sentiment is always 0.0 in pure backtest mode.
    """
    if not strategy:
        return False

    # Strategy must pass review
    instrument = market.get("instrument", "EURUSD")
    if not review_strategy(strategy, market, instrument):
        return False

    # Sentiment conflict check
    direction = strategy["direction"]
    if direction == "buy" and news_sentiment < -0.5:
        return False
    if direction == "sell" and news_sentiment > 0.5:
        return False

    return True


# ── Trade level calculation ───────────────────────────────────────────────────

def compute_entry_levels(
    instrument: str,
    direction: str,
    entry_price: float,
    sl_pips: float = 10.0,
    tp_pips: float = 20.0,
) -> dict:
    return {
        "entry_price": entry_price,
        "stop_loss": calculate_sl_price(entry_price, direction, sl_pips, instrument),
        "take_profit": calculate_tp_price(entry_price, direction, tp_pips, instrument),
        "sl_pips": sl_pips,
        "tp_pips": tp_pips,
    }
