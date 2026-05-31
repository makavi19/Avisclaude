"""
MT5 Broker — live trading via MetaTrader 5 Python API.

Requirements:
  - Windows 10/11 only (MT5 Python lib is Windows-only)
  - MetaTrader 5 terminal installed and running
  - pip install MetaTrader5
  - XM account logged-in inside the terminal

Usage:
  broker = MT5Broker(login=12345678, password="yourpass", server="XM-Real")
  await broker.connect()
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

from utils.pip_calculator import (
    get_pip_size, calculate_sl_price, calculate_tp_price,
    price_to_pips, get_price_decimals,
)

# Timeframe mapping: our string → MT5 constant (imported lazily)
_TF_MAP: dict[str, int] = {}  # populated on first use

# Magic number identifies orders placed by this bot
DEFAULT_MAGIC = 20240001


def _get_mt5():
    """Lazy import so the file can be imported on non-Windows machines without crashing."""
    try:
        import MetaTrader5 as mt5
        return mt5
    except ImportError:
        raise ImportError(
            "MetaTrader5 package not installed.\n"
            "Run: pip install MetaTrader5\n"
            "Note: MT5 Python API only works on Windows."
        )


def _tf_const(timeframe: str) -> int:
    mt5 = _get_mt5()
    mapping = {
        "M1": mt5.TIMEFRAME_M1,
        "M5": mt5.TIMEFRAME_M5,
        "M15": mt5.TIMEFRAME_M15,
        "M30": mt5.TIMEFRAME_M30,
        "H1": mt5.TIMEFRAME_H1,
        "H4": mt5.TIMEFRAME_H4,
        "D1": mt5.TIMEFRAME_D1,
    }
    return mapping.get(timeframe.upper(), mt5.TIMEFRAME_M15)


class MT5Broker:
    """
    Live broker implementation using MetaTrader5 Python API.
    Drop-in replacement for MockBroker.
    All blocking MT5 calls are wrapped in asyncio.to_thread().
    """

    def __init__(
        self,
        login: int,
        password: str,
        server: str,
        magic: int = DEFAULT_MAGIC,
        lot_size: float = 0.01,
    ):
        self.login = login
        self.password = password
        self.server = server
        self.magic = magic
        self.lot_size = lot_size
        self._connected = False
        # Map trade_id (str) → MT5 position ticket (int)
        self._ticket_map: dict[str, int] = {}

    # ─── Connection ───────────────────────────────────────────────────────────

    async def connect(self) -> bool:
        return await asyncio.to_thread(self._connect_sync)

    def _connect_sync(self) -> bool:
        mt5 = _get_mt5()
        if not mt5.initialize():
            raise ConnectionError(f"MT5 initialize() failed: {mt5.last_error()}")
        if not mt5.login(self.login, self.password, self.server):
            raise ConnectionError(
                f"MT5 login failed for account {self.login} on {self.server}: {mt5.last_error()}"
            )
        info = mt5.account_info()
        print(
            f"  MT5 connected: {info.name} | {self.server} | "
            f"Balance: {info.balance} {info.currency}"
        )
        self._connected = True
        return True

    async def disconnect(self) -> None:
        await asyncio.to_thread(_get_mt5().shutdown)
        self._connected = False

    # ─── Market data ──────────────────────────────────────────────────────────

    async def get_ohlcv(self, instrument: str, timeframe: str, count: int = 200) -> dict:
        return await asyncio.to_thread(self._get_ohlcv_sync, instrument, timeframe, count)

    def _get_ohlcv_sync(self, instrument: str, timeframe: str, count: int) -> dict:
        mt5 = _get_mt5()
        rates = mt5.copy_rates_from_pos(instrument, _tf_const(timeframe), 0, count)
        if rates is None or len(rates) == 0:
            raise ValueError(
                f"No OHLCV data for {instrument} {timeframe}. "
                f"Is the symbol visible in Market Watch? MT5 error: {mt5.last_error()}"
            )
        candles = [
            {
                "timestamp": datetime.utcfromtimestamp(r["time"]).isoformat(),
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
                f"Cannot get tick for {instrument}. "
                f"Make sure it is in Market Watch. Error: {mt5.last_error()}"
            )
        pip_size = get_pip_size(instrument)
        spread_pips = round((tick.ask - tick.bid) / pip_size, 1)
        return {
            "instrument": instrument,
            "bid": tick.bid,
            "ask": tick.ask,
            "mid": round((tick.bid + tick.ask) / 2, 5),
            "spread_pips": spread_pips,
        }

    # ─── Trading ──────────────────────────────────────────────────────────────

    def calculate_trade_levels(
        self,
        instrument: str,
        direction: str,
        entry_price: float,
        sl_pips: float = 10.0,
        tp_pips: float = 20.0,
    ) -> dict:
        """Pure maths — no MT5 call needed."""
        sl = calculate_sl_price(entry_price, direction, sl_pips, instrument)
        tp = calculate_tp_price(entry_price, direction, tp_pips, instrument)
        return {
            "instrument": instrument,
            "direction": direction,
            "entry_price": entry_price,
            "stop_loss": sl,
            "take_profit": tp,
            "sl_pips": sl_pips,
            "tp_pips": tp_pips,
            "pip_size": get_pip_size(instrument),
        }

    def place_order(
        self,
        instrument: str,
        direction: str,
        entry_price: float,
        stop_loss: float,
        take_profit: float,
        lot_size: float = None,
        strategy_name: str = "master_bot",
    ) -> dict:
        """Synchronous wrapper — called via asyncio.to_thread in async context."""
        return asyncio.get_event_loop().run_until_complete(
            asyncio.to_thread(
                self._place_order_sync,
                instrument, direction, entry_price,
                stop_loss, take_profit,
                lot_size or self.lot_size,
                strategy_name,
            )
        )

    def _place_order_sync(
        self,
        instrument: str,
        direction: str,
        entry_price: float,
        stop_loss: float,
        take_profit: float,
        lot_size: float,
        strategy_name: str,
    ) -> dict:
        mt5 = _get_mt5()

        # Get fresh fill price
        tick = mt5.symbol_info_tick(instrument)
        if tick is None:
            return {"status": "failed", "error": f"Cannot get tick for {instrument}"}

        order_type = mt5.ORDER_TYPE_BUY if direction == "buy" else mt5.ORDER_TYPE_SELL
        fill_price = tick.ask if direction == "buy" else tick.bid

        # XM supports ORDER_FILLING_IOC; fall back to FOK if needed
        symbol_info = mt5.symbol_info(instrument)
        filling_mode = mt5.ORDER_FILLING_IOC
        if symbol_info and symbol_info.filling_mode == 1:
            filling_mode = mt5.ORDER_FILLING_FOK

        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": instrument,
            "volume": lot_size,
            "type": order_type,
            "price": fill_price,
            "sl": stop_loss,
            "tp": take_profit,
            "deviation": 20,       # max slippage in points
            "magic": self.magic,
            "comment": strategy_name[:31],
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": filling_mode,
        }

        result = mt5.order_send(request)
        if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
            code = result.retcode if result else "None"
            comment = result.comment if result else mt5.last_error()
            return {
                "status": "failed",
                "error": f"MT5 order_send failed: retcode={code} comment={comment}",
            }

        trade_id = f"MT5-{result.order}"
        self._ticket_map[trade_id] = result.order

        pip_size = get_pip_size(instrument)
        actual_entry = result.price
        slippage_pips = round(abs(actual_entry - fill_price) / pip_size, 2)

        return {
            "trade_id": trade_id,
            "status": "placed",
            "actual_entry_price": actual_entry,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "lot_size": lot_size,
            "slippage_pips": slippage_pips,
            "mt5_ticket": result.order,
            "message": f"MT5 order placed: ticket={result.order}",
        }

    def get_trade_status(self, trade_id: str) -> dict:
        mt5 = _get_mt5()
        ticket = self._ticket_map.get(trade_id)
        if ticket is None:
            return {"error": f"Unknown trade_id: {trade_id}", "status": "unknown"}

        positions = mt5.positions_get(ticket=ticket)
        if positions:
            pos = positions[0]
            instrument = pos.symbol
            pip_size = get_pip_size(instrument)
            tick = mt5.symbol_info_tick(instrument)
            current_price = (tick.bid if pos.type == 0 else tick.ask) if tick else pos.price_current
            direction = "buy" if pos.type == 0 else "sell"
            pnl_pips = round(
                (current_price - pos.price_open) / pip_size if direction == "buy"
                else (pos.price_open - current_price) / pip_size,
                2,
            )
            return {
                "trade_id": trade_id,
                "status": "open",
                "instrument": pos.symbol,
                "direction": direction,
                "entry_price": pos.price_open,
                "current_price": current_price,
                "stop_loss": pos.sl,
                "take_profit": pos.tp,
                "pnl_pips": pnl_pips,
                "lot_size": pos.volume,
                "mt5_ticket": ticket,
            }

        # Position closed — check deal history
        from_time = datetime(2020, 1, 1)
        to_time = datetime.utcnow()
        deals = mt5.history_deals_get(
            from_time, to_time, position=ticket
        )
        if deals:
            last = deals[-1]
            return {
                "trade_id": trade_id,
                "status": "closed",
                "close_price": last.price,
                "pnl_pips": None,
                "mt5_ticket": ticket,
            }
        return {"trade_id": trade_id, "status": "unknown"}

    def modify_stop_loss(self, trade_id: str, new_stop_loss: float) -> dict:
        mt5 = _get_mt5()
        ticket = self._ticket_map.get(trade_id)
        if ticket is None:
            return {"error": f"Unknown trade_id: {trade_id}"}

        positions = mt5.positions_get(ticket=ticket)
        if not positions:
            return {"error": f"Position {ticket} not found"}
        pos = positions[0]

        request = {
            "action": mt5.TRADE_ACTION_SLTP,
            "symbol": pos.symbol,
            "sl": new_stop_loss,
            "tp": pos.tp,
            "position": ticket,
        }
        result = mt5.order_send(request)
        if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
            code = result.retcode if result else "None"
            return {
                "error": f"SL modify failed: retcode={code}",
                "trade_id": trade_id,
            }
        return {
            "trade_id": trade_id,
            "old_stop_loss": pos.sl,
            "new_stop_loss": new_stop_loss,
            "status": "modified",
        }

    def close_trade(self, trade_id: str, reason: str) -> dict:
        mt5 = _get_mt5()
        ticket = self._ticket_map.get(trade_id)
        if ticket is None:
            return {"error": f"Unknown trade_id: {trade_id}"}

        positions = mt5.positions_get(ticket=ticket)
        if not positions:
            return {"trade_id": trade_id, "status": "already_closed"}
        pos = positions[0]

        tick = mt5.symbol_info_tick(pos.symbol)
        close_type = mt5.ORDER_TYPE_SELL if pos.type == 0 else mt5.ORDER_TYPE_BUY
        close_price = tick.bid if close_type == mt5.ORDER_TYPE_SELL else tick.ask

        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": pos.symbol,
            "volume": pos.volume,
            "type": close_type,
            "position": ticket,
            "price": close_price,
            "deviation": 20,
            "magic": self.magic,
            "comment": f"bot_close:{reason[:20]}",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }
        result = mt5.order_send(request)
        if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
            code = result.retcode if result else "None"
            return {"error": f"Close failed: retcode={code}", "trade_id": trade_id}

        return {
            "trade_id": trade_id,
            "status": "closed",
            "close_price": close_price,
            "reason": reason,
            "mt5_ticket": ticket,
        }
