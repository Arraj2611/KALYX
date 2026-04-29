"""
Strategy API router.
"""
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
from sqlalchemy.orm import Session
from datetime import datetime

from app.data.database import get_db_session
from app.strategies.service import StrategyService
from app.strategies.backtesting import BacktestEngine

router = APIRouter()


class StrategyConfig(BaseModel):
    """Strategy configuration model."""
    name: str
    description: Optional[str] = None
    strategy_type: str
    config: Dict[str, Any]
    code: Optional[str] = None


class StrategyResponse(BaseModel):
    """Strategy response model."""
    id: int
    name: str
    description: Optional[str]
    strategy_type: str
    config: Dict[str, Any]
    is_active: bool
    created_at: str
    updated_at: Optional[str]


class BacktestRequest(BaseModel):
    """Backtest request model."""
    strategy_id: int
    start_date: datetime
    end_date: datetime
    initial_capital: float = 100000.0
    config: Optional[Dict[str, Any]] = None


@router.get("/", response_model=List[StrategyResponse])
async def list_strategies(db: Session = Depends(get_db_session)):
    """List all strategies."""
    service = StrategyService(db)
    strategies = service.list_strategies()
    return strategies


@router.post("/", response_model=StrategyResponse)
async def create_strategy(
    strategy: StrategyConfig,
    db: Session = Depends(get_db_session)
):
    """Create a new strategy."""
    service = StrategyService(db)
    try:
        created = service.create_strategy(
            name=strategy.name,
            description=strategy.description,
            strategy_type=strategy.strategy_type,
            config=strategy.config,
            code=strategy.code
        )
        return created
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{strategy_id}", response_model=StrategyResponse)
async def get_strategy(
    strategy_id: int,
    db: Session = Depends(get_db_session)
):
    """Get strategy by ID."""
    service = StrategyService(db)
    strategy = service.get_strategy(strategy_id)
    if not strategy:
        raise HTTPException(status_code=404, detail="Strategy not found")
    return strategy


@router.put("/{strategy_id}", response_model=StrategyResponse)
async def update_strategy(
    strategy_id: int,
    strategy: StrategyConfig,
    db: Session = Depends(get_db_session)
):
    """Update strategy."""
    service = StrategyService(db)
    try:
        updated = service.update_strategy(
            strategy_id=strategy_id,
            name=strategy.name,
            description=strategy.description,
            config=strategy.config,
            code=strategy.code
        )
        return updated
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/{strategy_id}")
async def delete_strategy(
    strategy_id: int,
    db: Session = Depends(get_db_session)
):
    """Delete strategy."""
    service = StrategyService(db)
    try:
        service.delete_strategy(strategy_id)
        return {"success": True}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{strategy_id}/activate")
async def activate_strategy(
    strategy_id: int,
    db: Session = Depends(get_db_session)
):
    """Activate a strategy."""
    service = StrategyService(db)
    try:
        service.activate_strategy(strategy_id)
        return {"success": True}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{strategy_id}/deactivate")
async def deactivate_strategy(
    strategy_id: int,
    db: Session = Depends(get_db_session)
):
    """Deactivate a strategy."""
    service = StrategyService(db)
    try:
        service.deactivate_strategy(strategy_id)
        return {"success": True}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{strategy_id}/export")
async def export_strategy(
    strategy_id: int,
    db: Session = Depends(get_db_session)
):
    """Export strategy as JSON."""
    service = StrategyService(db)
    try:
        exported = service.export_strategy(strategy_id)
        return exported
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/import")
async def import_strategy(
    strategy_data: Dict[str, Any],
    db: Session = Depends(get_db_session)
):
    """Import strategy from JSON."""
    service = StrategyService(db)
    try:
        imported = service.import_strategy(strategy_data)
        return imported
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/backtest")
async def run_backtest(
    request: BacktestRequest,
    db: Session = Depends(get_db_session)
):
    """Run backtest on a strategy."""
    # This would need historical data loading
    # For now, return a placeholder
    return {
        "message": "Backtest endpoint - requires historical data integration",
        "strategy_id": request.strategy_id,
        "start_date": request.start_date.isoformat(),
        "end_date": request.end_date.isoformat()
    }
