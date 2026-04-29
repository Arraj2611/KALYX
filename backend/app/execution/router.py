"""
Execution API router.
"""
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import List, Optional
from sqlalchemy.orm import Session

from app.data.database import get_db_session
from app.execution.service import ExecutionService
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


class OrderRequest(BaseModel):
    """Order request model."""
    tradingsymbol: str
    exchange: str = "NFO"
    transaction_type: str  # BUY, SELL
    quantity: int
    order_type: str = "MARKET"  # MARKET, LIMIT, SL, SL-M
    product: str = "MIS"  # MIS, NRML, CNC
    price: Optional[float] = None
    trigger_price: Optional[float] = None
    strategy_id: Optional[int] = None


class OrderResponse(BaseModel):
    """Order response model."""
    id: int
    order_id: str
    tradingsymbol: str
    status: str
    quantity: int
    filled_quantity: int
    average_price: Optional[float]
    created_at: str


@router.post("/order", response_model=OrderResponse)
async def place_order(
    order: OrderRequest,
    account_name: str = "paper_test",
    db: Session = Depends(get_db_session)
):
    """Place a new order."""
    adapter = _get_adapter(account_name)
    service = ExecutionService(db, adapter)
    try:
        result = await service.place_order(
            tradingsymbol=order.tradingsymbol,
            exchange=order.exchange,
            transaction_type=order.transaction_type,
            quantity=order.quantity,
            order_type=order.order_type,
            product=order.product,
            price=order.price,
            trigger_price=order.trigger_price,
            strategy_id=order.strategy_id
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/orders", response_model=List[OrderResponse])
async def get_orders(
    account_name: str = "paper_test",
    status: Optional[str] = None,
    strategy_id: Optional[int] = None,
    db: Session = Depends(get_db_session)
):
    """Get orders."""
    adapter = _get_adapter(account_name)
    service = ExecutionService(db, adapter)
    orders = service.get_orders(status=status, strategy_id=strategy_id)
    return orders


@router.get("/orders/{order_id}", response_model=OrderResponse)
async def get_order(
    order_id: str,
    account_name: str = "paper_test",
    db: Session = Depends(get_db_session)
):
    """Get order by ID."""
    adapter = _get_adapter(account_name)
    service = ExecutionService(db, adapter)
    order = service.get_order(order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    return order


@router.post("/orders/{order_id}/cancel")
async def cancel_order(
    order_id: str,
    account_name: str = "paper_test",
    db: Session = Depends(get_db_session)
):
    """Cancel an order."""
    adapter = _get_adapter(account_name)
    service = ExecutionService(db, adapter)
    try:
        result = await service.cancel_order(order_id)
        return {"success": True, "order_id": result}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/positions")
async def get_positions(
    account_name: str = "paper_test",
    db: Session = Depends(get_db_session)
):
    """Get current positions."""
    adapter = _get_adapter(account_name)
    service = ExecutionService(db, adapter)
    try:
        positions = await service.get_positions()
        return positions
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
