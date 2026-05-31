from pydantic import BaseModel, Field
from enum import Enum
from typing import Optional, Any
from datetime import datetime

from models.market_state import MarketState
from models.trade import LiveTrade, TradeDirection


class AgentStatus(str, Enum):
    SUCCESS = "success"
    FAILURE = "failure"
    PENDING = "pending"
    RUNNING = "running"


class AgentDecision(BaseModel):
    agent_name: str
    status: AgentStatus
    output: dict[str, Any] = Field(default_factory=dict)
    reasoning: str = ""
    confidence: float = Field(ge=0.0, le=1.0, default=0.5)
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    tool_calls_made: list[str] = Field(default_factory=list)


class StrategyType(str, Enum):
    TREND_FOLLOWING = "trend_following"
    RANGE = "range"
    BREAKOUT = "breakout"
    REVERSAL = "reversal"


class StrategyProposal(BaseModel):
    strategy_type: StrategyType
    direction: TradeDirection
    rationale: str
    confidence: float = Field(ge=0.0, le=1.0)
    supporting_indicators: list[str] = Field(default_factory=list)
    risk_level: str = "medium"


class ReviewDecision(BaseModel):
    approved: bool
    review_notes: str
    historical_win_rate: float = 0.5
    suggested_improvements: Optional[str] = None
    rejection_reason: Optional[str] = None


class NewsAssessment(BaseModel):
    sentiment: str = "neutral"
    sentiment_score: float = Field(default=0.0, ge=-1.0, le=1.0)
    high_impact_events: list[str] = Field(default_factory=list)
    news_summary: str = ""
    trade_recommendation: str = "proceed"
    sentiment_conflict: bool = False


class ConfirmationDecision(BaseModel):
    decision: str  # "GO" | "NO_GO"
    reasoning: str
    risk_score: float = Field(default=0.5, ge=0.0, le=1.0)
    conditions: list[str] = Field(default_factory=list)


class PipelineContext(BaseModel):
    instrument: str
    timeframe: str
    run_id: str
    market_state: Optional[MarketState] = None
    strategy_proposal: Optional[StrategyProposal] = None
    review_decision: Optional[ReviewDecision] = None
    news_assessment: Optional[NewsAssessment] = None
    confirmation: Optional[ConfirmationDecision] = None
    live_trade: Optional[LiveTrade] = None
    agent_log: list[AgentDecision] = Field(default_factory=list)
    strategy_attempt_count: int = 0
    pipeline_status: str = "running"
    stage_statuses: dict[str, str] = Field(default_factory=dict)
    error_message: Optional[str] = None
