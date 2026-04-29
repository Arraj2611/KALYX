"""SQLAlchemy model for decision logging.

Every trading decision — executed, skipped, blocked, rejected, or failed —
is persisted here for post-session analysis and self-learning.
"""

from enum import Enum

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
)
from sqlalchemy.sql import func

from app.data.database import Base


class DecisionAction(str, Enum):
    """Possible outcomes of a trading decision evaluation."""

    EXECUTED = "executed"
    SKIPPED = "skipped"
    BLOCKED = "blocked"
    REJECTED = "rejected"
    FAILED = "failed"


class DecisionLog(Base):
    """Persists every signal evaluation with full context and outcome.

    Columns
    -------
    id              : surrogate PK
    timestamp       : when the decision was made (UTC)
    account_name    : e.g. "paper_test", "zerodha_prod"
    symbol          : trading symbol, e.g. "NIFTY25JANFUT"
    signal          : e.g. "LONG", "SHORT", "EXIT"
    strategy_id     : FK → strategies.id (nullable — manual / unknown strategy)
    confidence      : float 0-1 from the strategy model
    market_state    : JSON snapshot of indicators at decision time
    action          : DecisionAction enum value
    reasoning       : full natural-language explanation
    skip_reason     : short machine-readable code when not executed
    trade_id        : FK → trades.id (set when a trade was placed)
    outcome_if_taken: hypothetical P&L (filled during hindsight analysis)
    outcome_actual  : realised P&L (filled after position closes)
    was_correct     : True if decision was good in hindsight
    trade_context   : JSON snapshot of the TradeContext dataclass
    """

    __tablename__ = "decision_log"

    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True,
    )

    # Who / what
    account_name = Column(String, nullable=False, index=True)
    symbol = Column(String, nullable=False, index=True)
    signal = Column(String, nullable=False)
    strategy_id = Column(
        Integer, ForeignKey("strategies.id", ondelete="SET NULL"), nullable=True
    )
    confidence = Column(Float, nullable=False)
    market_state = Column(JSON, nullable=True)

    # Decision
    action = Column(String, nullable=False, index=True)
    reasoning = Column(Text, nullable=False)
    skip_reason = Column(String, nullable=True)

    # Linked trade (only set for EXECUTED)
    trade_id = Column(
        Integer, ForeignKey("trades.id", ondelete="SET NULL"), nullable=True
    )

    # Hindsight (filled later by fill_hindsight)
    outcome_if_taken = Column(Float, nullable=True)
    outcome_actual = Column(Float, nullable=True)
    was_correct = Column(Boolean, nullable=True)

    # Full context snapshot
    trade_context = Column(JSON, nullable=True)
