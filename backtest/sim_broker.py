"""
Simulated broker for backtesting.
Fills orders at next-bar open, checks SL/TP against bar High/Low.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from utils.pip_calculator import (
    get_pip_size, price_to_pips, compute_trailing_stop, get_price_decimals,
)


@dataclass
class BacktestTrade:
    trade_id: str
    instrument: str
    direction: str          # "buy" | "sell"
    strategy_type: str
    entry_time: datetime
    entry_price: float
    stop_loss: float
    take_profit: float
    initial_sl: float       # original SL (never changes)
    lot_size: float = 0.01

    current_sl: float = field(init=False)
    current_price: float = field(init=False)
    pnl_pips: float = 0.0
    breakeven_activated: bool = False
    trailing_active: bool = False
    max_pnl_pips: float = 0.0   # high water mark

    status: str = "open"        # "open" | "closed_tp" | "closed_sl" | "closed_eod"
    exit_time: Optional[datetime] = None
    exit_price: Optional[float] = None
    exit_reason: Optional[str] = None

    def __post_init__(self):
        self.current_sl = self.stop_loss
        self.current_price = self.entry_price


class SimBroker:
    """
    Backtesting broker.
    All prices come from historical bar data — no API calls.
    """

    def __init__(
        self,
        instrument: str,
        sl_pips: float = 10.0,
        tp_pips: float = 20.0,
        trailing_distance_pips: float = 10.0,
        breakeven_trigger_pips: float = 10.0,
        lot_size: float = 0.01,
        max_spread_pips: float = 3.0,
    ):
        self.instrument = instrument
        self.sl_pips = sl_pips
        self.tp_pips = tp_pips
        self.trailing_distance_pips = trailing_distance_pips
        self.breakeven_trigger_pips = breakeven_trigger_pips
        self.lot_size = lot_size
        self.max_spread_pips = max_spread_pips

        self.open_trade: Optional[BacktestTrade] = None
        self.closed_trades: list[BacktestTrade] = []
        self.pip_size = get_pip_size(instrument)
        self._decimals = get_price_decimals(instrument)

    # ── Order entry ───────────────────────────────────────────────────────────

    def try_open(
        self,
        entry_bar: dict,       # {"datetime", "open", "high", "low", "close"}
        direction: str,
        stop_loss: float,
        take_profit: float,
        strategy_type: str,
    ) -> Optional[BacktestTrade]:
        """Fill at next bar's open (entry_bar is the bar AFTER the signal bar)."""
        if self.open_trade is not None:
            return None  # already in a trade

        fill_price = entry_bar["open"]

        # Reject if spread too wide (simulated spread = 1.5 pips for major pairs)
        spread = 1.5 * self.pip_size
        actual_entry = round(
            fill_price + spread if direction == "buy" else fill_price - spread,
            self._decimals,
        )

        trade = BacktestTrade(
            trade_id=f"BT-{str(uuid.uuid4())[:6].upper()}",
            instrument=self.instrument,
            direction=direction,
            strategy_type=strategy_type,
            entry_time=entry_bar["datetime"],
            entry_price=actual_entry,
            stop_loss=stop_loss,
            take_profit=take_profit,
            initial_sl=stop_loss,
            lot_size=self.lot_size,
        )
        self.open_trade = trade
        return trade

    # ── Bar-by-bar update ─────────────────────────────────────────────────────

    def update_bar(self, bar: dict) -> Optional[BacktestTrade]:
        """
        Process one 1-minute bar against the open trade.
        Returns the trade if it was closed, else None.
        """
        trade = self.open_trade
        if trade is None:
            return None

        hi = bar["high"]
        lo = bar["low"]
        close = bar["close"]
        bar_time = bar["datetime"]

        direction = trade.direction

        # Update current price & PnL
        trade.current_price = close
        if direction == "buy":
            raw_pnl = price_to_pips(close - trade.entry_price, self.instrument)
        else:
            raw_pnl = price_to_pips(trade.entry_price - close, self.instrument)
        trade.pnl_pips = round(raw_pnl, 2)
        trade.max_pnl_pips = max(trade.max_pnl_pips, trade.pnl_pips)

        # Check SL hit (use Low for BUY, High for SELL)
        if direction == "buy" and lo <= trade.current_sl:
            return self._close_trade(trade, trade.current_sl, bar_time, "sl_hit")
        if direction == "sell" and hi >= trade.current_sl:
            return self._close_trade(trade, trade.current_sl, bar_time, "sl_hit")

        # Check TP hit (use High for BUY, Low for SELL)
        if direction == "buy" and hi >= trade.take_profit:
            return self._close_trade(trade, trade.take_profit, bar_time, "tp_hit")
        if direction == "sell" and lo <= trade.take_profit:
            return self._close_trade(trade, trade.take_profit, bar_time, "tp_hit")

        # Update trailing stop
        result = compute_trailing_stop(
            instrument=self.instrument,
            direction=direction,
            entry_price=trade.entry_price,
            current_price=close,
            current_sl=trade.current_sl,
            breakeven_activated=trade.breakeven_activated,
            trailing_distance_pips=self.trailing_distance_pips,
            breakeven_trigger_pips=self.breakeven_trigger_pips,
        )
        if result["sl_moved"]:
            trade.current_sl = result["new_sl"]
            trade.breakeven_activated = result["breakeven_activated"]
            trade.trailing_active = result["trailing_active"]

        return None

    def force_close(self, bar: dict, reason: str = "end_of_session") -> Optional[BacktestTrade]:
        """Close any open trade at bar close (e.g. end of day)."""
        if self.open_trade is None:
            return None
        return self._close_trade(self.open_trade, bar["close"], bar["datetime"], reason)

    def _close_trade(
        self, trade: BacktestTrade, exit_price: float, exit_time: datetime, reason: str
    ) -> BacktestTrade:
        direction = trade.direction
        if direction == "buy":
            trade.pnl_pips = round(
                price_to_pips(exit_price - trade.entry_price, self.instrument), 2
            )
        else:
            trade.pnl_pips = round(
                price_to_pips(trade.entry_price - exit_price, self.instrument), 2
            )
        trade.exit_price = exit_price
        trade.exit_time = exit_time
        trade.exit_reason = reason
        trade.status = reason  # "sl_hit" | "tp_hit" | "end_of_session"
        self.closed_trades.append(trade)
        self.open_trade = None
        return trade
