import uuid
from datetime import datetime
from typing import Any

from utils.pip_calculator import (
    get_pip_size, calculate_sl_price, calculate_tp_price,
    price_to_pips, get_price_decimals,
)

TRADING_TOOLS = [
    {
        "name": "calculate_trade_levels",
        "description": (
            "Given entry price, direction, and instrument, compute exact stop loss and take profit "
            "prices enforcing the hard rules: SL=10 pips, TP=20 pips."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "instrument": {"type": "string"},
                "direction": {"type": "string", "enum": ["buy", "sell"]},
                "entry_price": {"type": "number"},
                "sl_pips": {"type": "number", "default": 10},
                "tp_pips": {"type": "number", "default": 20},
            },
            "required": ["instrument", "direction", "entry_price"],
        },
    },
    {
        "name": "place_order",
        "description": "Submit a market order. Returns a trade_id on success.",
        "input_schema": {
            "type": "object",
            "properties": {
                "instrument": {"type": "string"},
                "direction": {"type": "string", "enum": ["buy", "sell"]},
                "entry_price": {"type": "number"},
                "stop_loss": {"type": "number"},
                "take_profit": {"type": "number"},
                "lot_size": {"type": "number", "default": 0.1},
                "strategy_name": {"type": "string"},
            },
            "required": ["instrument", "direction", "entry_price", "stop_loss", "take_profit"],
        },
    },
    {
        "name": "get_trade_status",
        "description": "Get current status and P&L of an open trade by trade_id.",
        "input_schema": {
            "type": "object",
            "properties": {
                "trade_id": {"type": "string"},
            },
            "required": ["trade_id"],
        },
    },
    {
        "name": "close_trade",
        "description": "Manually close an open trade at current market price.",
        "input_schema": {
            "type": "object",
            "properties": {
                "trade_id": {"type": "string"},
                "reason": {"type": "string"},
            },
            "required": ["trade_id", "reason"],
        },
    },
    {
        "name": "modify_stop_loss",
        "description": "Modify the stop loss of an open trade.",
        "input_schema": {
            "type": "object",
            "properties": {
                "trade_id": {"type": "string"},
                "new_stop_loss": {"type": "number"},
            },
            "required": ["trade_id", "new_stop_loss"],
        },
    },
]


class MockBroker:
    def __init__(self):
        self._trades: dict[str, dict[str, Any]] = {}
        self._price_tick: int = 0

    def calculate_trade_levels(
        self,
        instrument: str,
        direction: str,
        entry_price: float,
        sl_pips: float = 10.0,
        tp_pips: float = 20.0,
    ) -> dict:
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
        lot_size: float = 0.1,
        strategy_name: str = "unknown",
    ) -> dict:
        # Simulate 0.3 pip slippage
        pip_size = get_pip_size(instrument)
        decimals = get_price_decimals(instrument)
        slippage = 0.3 * pip_size
        actual_entry = round(
            entry_price + slippage if direction == "buy" else entry_price - slippage,
            decimals,
        )
        trade_id = f"TRD-{str(uuid.uuid4())[:6].upper()}"
        self._trades[trade_id] = {
            "trade_id": trade_id,
            "instrument": instrument,
            "direction": direction,
            "entry_price": actual_entry,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "lot_size": lot_size,
            "strategy_name": strategy_name,
            "status": "open",
            "open_time": datetime.utcnow().isoformat(),
            "current_price": actual_entry,
            "pnl_pips": 0.0,
        }
        return {
            "trade_id": trade_id,
            "status": "placed",
            "actual_entry_price": actual_entry,
            "slippage_pips": round(price_to_pips(abs(actual_entry - entry_price), instrument), 2),
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "message": f"Order placed successfully for {instrument} {direction.upper()}",
        }

    def get_trade_status(self, trade_id: str) -> dict:
        trade = self._trades.get(trade_id)
        if not trade:
            return {"error": f"Trade {trade_id} not found", "status": "unknown"}

        # Simulate price movement (gradual drift toward TP in mock)
        self._price_tick += 1
        pip_size = get_pip_size(trade["instrument"])
        decimals = get_price_decimals(trade["instrument"])
        drift = self._price_tick * 1.5 * pip_size
        direction = trade["direction"]
        current_price = round(
            trade["entry_price"] + drift if direction == "buy" else trade["entry_price"] - drift,
            decimals,
        )
        pnl_pips = price_to_pips(
            (current_price - trade["entry_price"]) if direction == "buy"
            else (trade["entry_price"] - current_price),
            trade["instrument"],
        )

        # Check if SL or TP hit
        if direction == "buy":
            if current_price <= trade["stop_loss"]:
                trade["status"] = "closed_sl"
            elif current_price >= trade["take_profit"]:
                trade["status"] = "closed_tp"
        else:
            if current_price >= trade["stop_loss"]:
                trade["status"] = "closed_sl"
            elif current_price <= trade["take_profit"]:
                trade["status"] = "closed_tp"

        trade["current_price"] = current_price
        trade["pnl_pips"] = round(pnl_pips, 2)
        return {**trade}

    def close_trade(self, trade_id: str, reason: str) -> dict:
        trade = self._trades.get(trade_id)
        if not trade:
            return {"error": f"Trade {trade_id} not found"}
        trade["status"] = "closed_manual"
        trade["close_reason"] = reason
        trade["close_time"] = datetime.utcnow().isoformat()
        return {
            "trade_id": trade_id,
            "status": "closed_manual",
            "reason": reason,
            "pnl_pips": trade["pnl_pips"],
        }

    def modify_stop_loss(self, trade_id: str, new_stop_loss: float) -> dict:
        trade = self._trades.get(trade_id)
        if not trade:
            return {"error": f"Trade {trade_id} not found"}
        old_sl = trade["stop_loss"]
        trade["stop_loss"] = new_stop_loss
        return {
            "trade_id": trade_id,
            "old_stop_loss": old_sl,
            "new_stop_loss": new_stop_loss,
            "status": "modified",
        }
