"""
Decisions API router — read-only access to the decision log.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from typing import List, Optional, Any
from datetime import datetime
from sqlalchemy.orm import Session

from app.data.database import get_db_session
from app.decisions.models import DecisionLog

router = APIRouter()


class DecisionLogResponse(BaseModel):
    """Decision log entry response."""
    id: int
    timestamp: datetime
    account_name: str
    symbol: str
    signal: str
    strategy_id: Optional[int]
    confidence: float
    action: str
    reasoning: str
    skip_reason: Optional[str]
    trade_id: Optional[int]
    outcome_if_taken: Optional[float]
    outcome_actual: Optional[float]
    was_correct: Optional[bool]
    market_state: Optional[Any]

    class Config:
        from_attributes = True


@router.get("/", response_model=List[DecisionLogResponse])
def list_decisions(
    account_name: Optional[str] = None,
    symbol: Optional[str] = None,
    action: Optional[str] = None,
    limit: int = Query(default=100, le=1000),
    db: Session = Depends(get_db_session),
):
    """List decision log entries, newest first."""
    query = db.query(DecisionLog)

    if account_name:
        query = query.filter(DecisionLog.account_name == account_name)
    if symbol:
        query = query.filter(DecisionLog.symbol == symbol)
    if action:
        query = query.filter(DecisionLog.action == action)

    entries = query.order_by(DecisionLog.timestamp.desc()).limit(limit).all()
    return entries


@router.get("/{decision_id}", response_model=DecisionLogResponse)
def get_decision(decision_id: int, db: Session = Depends(get_db_session)):
    """Get a single decision log entry by ID."""
    entry = db.query(DecisionLog).filter(DecisionLog.id == decision_id).first()
    if not entry:
        raise HTTPException(status_code=404, detail="Decision not found")
    return entry
