from utils.pip_calculator import (
    get_pip_size, price_to_pips, compute_trailing_stop, get_price_decimals,
)

RISK_TOOLS = [
    {
        "name": "calculate_trailing_stop",
        "description": (
            "Compute the new trailing stop loss price given current price, direction, and trade state. "
            "Implements three-state algorithm: Initial → Breakeven → Trailing."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "instrument": {"type": "string"},
                "direction": {"type": "string", "enum": ["buy", "sell"]},
                "entry_price": {"type": "number"},
                "current_price": {"type": "number"},
                "current_sl": {"type": "number"},
                "breakeven_activated": {"type": "boolean"},
                "trailing_distance_pips": {"type": "number", "default": 10},
                "breakeven_trigger_pips": {"type": "number", "default": 10},
            },
            "required": [
                "instrument", "direction", "entry_price",
                "current_price", "current_sl", "breakeven_activated",
            ],
        },
    },
    {
        "name": "get_pnl",
        "description": "Calculate current profit/loss in pips for a trade.",
        "input_schema": {
            "type": "object",
            "properties": {
                "instrument": {"type": "string"},
                "direction": {"type": "string", "enum": ["buy", "sell"]},
                "entry_price": {"type": "number"},
                "current_price": {"type": "number"},
            },
            "required": ["instrument", "direction", "entry_price", "current_price"],
        },
    },
    {
        "name": "check_risk_conditions",
        "description": "Evaluate whether a trade should be closed early based on rules.",
        "input_schema": {
            "type": "object",
            "properties": {
                "trade_id": {"type": "string"},
                "pnl_pips": {"type": "number"},
                "open_duration_minutes": {"type": "integer"},
                "current_price": {"type": "number"},
                "current_sl": {"type": "number"},
                "current_tp": {"type": "number"},
                "direction": {"type": "string", "enum": ["buy", "sell"]},
            },
            "required": [
                "trade_id", "pnl_pips", "open_duration_minutes",
                "current_price", "current_sl", "current_tp", "direction",
            ],
        },
    },
]


def calculate_trailing_stop_tool(
    instrument: str,
    direction: str,
    entry_price: float,
    current_price: float,
    current_sl: float,
    breakeven_activated: bool,
    trailing_distance_pips: float = 10.0,
    breakeven_trigger_pips: float = 10.0,
) -> dict:
    return compute_trailing_stop(
        instrument=instrument,
        direction=direction,
        entry_price=entry_price,
        current_price=current_price,
        current_sl=current_sl,
        breakeven_activated=breakeven_activated,
        trailing_distance_pips=trailing_distance_pips,
        breakeven_trigger_pips=breakeven_trigger_pips,
    )


def get_pnl_tool(
    instrument: str,
    direction: str,
    entry_price: float,
    current_price: float,
) -> dict:
    if direction == "buy":
        pnl_pips = price_to_pips(current_price - entry_price, instrument)
    else:
        pnl_pips = price_to_pips(entry_price - current_price, instrument)
    return {
        "instrument": instrument,
        "direction": direction,
        "entry_price": entry_price,
        "current_price": current_price,
        "pnl_pips": round(pnl_pips, 2),
        "pnl_direction": "profit" if pnl_pips > 0 else "loss",
    }


def check_risk_conditions_tool(
    trade_id: str,
    pnl_pips: float,
    open_duration_minutes: int,
    current_price: float,
    current_sl: float,
    current_tp: float,
    direction: str,
) -> dict:
    reasons = []
    should_close = False

    # Hard SL/TP check (broker normally handles, but verify)
    if pnl_pips <= -10.0:
        reasons.append("stop_loss_hit")
        should_close = True
    if pnl_pips >= 20.0:
        reasons.append("take_profit_hit")
        should_close = True

    # Time-based risk: close if open > 4 hours in mock
    if open_duration_minutes > 240:
        reasons.append("max_duration_exceeded")
        should_close = True

    # Gap check
    if direction == "buy" and current_price < current_sl:
        reasons.append("price_below_stop_loss")
        should_close = True
    if direction == "sell" and current_price > current_sl:
        reasons.append("price_above_stop_loss")
        should_close = True

    return {
        "trade_id": trade_id,
        "should_close": should_close,
        "reasons": reasons,
        "pnl_pips": pnl_pips,
        "assessment": "close_trade" if should_close else "continue_monitoring",
    }
