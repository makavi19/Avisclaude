from pydantic import BaseModel, Field
from enum import Enum
from typing import Optional
from datetime import datetime


class TradeDirection(str, Enum):
    BUY = "buy"
    SELL = "sell"


class TradeStatus(str, Enum):
    PENDING = "pending"
    OPEN = "open"
    CLOSED_TP = "closed_tp"
    CLOSED_SL = "closed_sl"
    CLOSED_MANUAL = "closed_manual"
    REJECTED = "rejected"


class TradeSignal(BaseModel):
    instrument: str
    direction: TradeDirection
    entry_price: float
    stop_loss: float
    take_profit: float
    stop_loss_pips: float = 10.0
    take_profit_pips: float = 20.0
    strategy_name: str
    signal_timestamp: datetime = Field(default_factory=datetime.utcnow)
    rationale: str


class LiveTrade(BaseModel):
    trade_id: str
    signal: TradeSignal
    actual_entry_price: float
    current_price: float
    current_sl: float
    current_tp: float
    lot_size: float = 0.1
    status: TradeStatus = TradeStatus.OPEN
    pnl_pips: float = 0.0
    breakeven_activated: bool = False
    trailing_active: bool = False
    open_time: datetime = Field(default_factory=datetime.utcnow)
    close_time: Optional[datetime] = None
    close_price: Optional[float] = None
    close_reason: Optional[str] = None
