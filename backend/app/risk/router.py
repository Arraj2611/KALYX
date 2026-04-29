"""
Risk management API router.
"""
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional
from sqlalchemy.orm import Session

from app.data.database import get_db_session
from app.risk.service import RiskService
from app.brokers.account_manager import AccountManager

router = APIRouter()

_account_manager: Optional[AccountManager] = None


def set_account_manager(manager: AccountManager) -> None:
    global _account_manager
    _account_manager = manager


def _get_adapter(account_name: str):
    if _account_manager is None:
        raise HTTPException(status_code=503, detail="AccountManager not initialized")
    try:
        return _account_manager.get_adapter(account_name)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Account '{account_name}' not found")


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
async def get_risk_status(
    account_name: str = "paper_test",
    db: Session = Depends(get_db_session)
):
    """Get current risk status."""
    adapter = _get_adapter(account_name)
    service = RiskService(db, adapter)
    try:
        status = await service.get_risk_status()
        return status
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/margins")
async def get_margins(
    account_name: str = "paper_test",
    db: Session = Depends(get_db_session)
):
    """Get current margin details."""
    adapter = _get_adapter(account_name)
    service = RiskService(db, adapter)
    try:
        margins = await service.get_margins()
        return margins
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/circuit-breaker/reset")
async def reset_circuit_breaker(
    account_name: str = "paper_test",
    db: Session = Depends(get_db_session)
):
    """Reset circuit breaker."""
    adapter = _get_adapter(account_name)
    service = RiskService(db, adapter)
    try:
        service.reset_circuit_breaker()
        return {"success": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
