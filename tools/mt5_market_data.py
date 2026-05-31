"""
MT5 Market Data Provider — real OHLCV and price data via MT5 terminal.
"""

from __future__ import annotations

import asyncio
from datetime import datetime

from tools.market_data import MarketDataProvider, compute_indicators
from utils.pip_calculator import get_pip_size


def _get_mt5():
    try:
        import MetaTrader5 as mt5
        return mt5
    except ImportError:
        raise ImportError(
            "MetaTrader5 package not installed. Run: pip install MetaTrader5\n"
            "Note: MT5 Python API only works on Windows."
        )


_TF_STR_MAP = {
    "M1": "TIMEFRAME_M1", "M5": "TIMEFRAME_M5",
    "M15": "TIMEFRAME_M15", "M30": "TIMEFRAME_M30",
    "H1": "TIMEFRAME_H1", "H4": "TIMEFRAME_H4", "D1": "TIMEFRAME_D1",
}


class MT5MarketDataProvider(MarketDataProvider):
    """
    Real market data from MT5 terminal.
    Symbol names must match exactly what XM shows in Market Watch,
    e.g. "EURUSD" or "EURUSDm" depending on your account type.
    """

    async def get_ohlcv(self, instrument: str, timeframe: str, count: int = 200) -> dict:
        return await asyncio.to_thread(self._get_ohlcv_sync, instrument, timeframe, count)

    def _get_ohlcv_sync(self, instrument: str, timeframe: str, count: int) -> dict:
        mt5 = _get_mt5()
        tf_attr = _TF_STR_MAP.get(timeframe.upper(), "TIMEFRAME_M15")
        tf_const = getattr(mt5, tf_attr)

        rates = mt5.copy_rates_from_pos(instrument, tf_const, 0, count)
        if rates is None or len(rates) == 0:
            raise ValueError(
                f"No data for {instrument} {timeframe}. "
                f"Is '{instrument}' in Market Watch? MT5 error: {mt5.last_error()}"
            )
        candles = [
            {
                "timestamp": datetime.utcfromtimestamp(int(r["time"])).isoformat(),
                "open": float(r["open"]),
                "high": float(r["high"]),
                "low": float(r["low"]),
                "close": float(r["close"]),
                "volume": float(r["tick_volume"]),
            }
            for r in rates
        ]
        return {"instrument": instrument, "timeframe": timeframe, "candles": candles}

    async def get_current_price(self, instrument: str) -> dict:
        return await asyncio.to_thread(self._get_price_sync, instrument)

    def _get_price_sync(self, instrument: str) -> dict:
        mt5 = _get_mt5()
        tick = mt5.symbol_info_tick(instrument)
        if tick is None:
            raise ValueError(
                f"Cannot get tick for '{instrument}'. "
                f"Add it to Market Watch in MT5. Error: {mt5.last_error()}"
            )
        pip_size = get_pip_size(instrument)
        return {
            "instrument": instrument,
            "bid": float(tick.bid),
            "ask": float(tick.ask),
            "mid": round((tick.bid + tick.ask) / 2, 5),
            "spread_pips": round((tick.ask - tick.bid) / pip_size, 1),
        }
