"""
Risk management API router.
"""
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional
from sqlalchemy.orm import Session

from app.data.database import get_db_session
from app.risk.service import RiskService

router = APIRouter()


class RiskStatusResponse(BaseModel):
    """Risk status response model."""
    capital_usage_pct: float
    daily_pnl: float
    daily_trades: int
    max_capital_usage_pct: float
    max_loss_per_day: float
    max_trades_per_day: int
    is_breach: bool
    circuit_breaker_active: bool
    available_margin: float
    used_margin: float


@router.get("/status", response_model=RiskStatusResponse)
async def get_risk_status(db: Session = Depends(get_db_session)):
    """Get current risk status."""
    service = RiskService(db)
    try:
        status = await service.get_risk_status()
        return status
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/margins")
async def get_margins(db: Session = Depends(get_db_session)):
    """Get current margin details."""
    service = RiskService(db)
    try:
        margins = await service.get_margins()
        return margins
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/circuit-breaker/reset")
async def reset_circuit_breaker(db: Session = Depends(get_db_session)):
    """Reset circuit breaker."""
    service = RiskService(db)
    try:
        service.reset_circuit_breaker()
        return {"success": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

