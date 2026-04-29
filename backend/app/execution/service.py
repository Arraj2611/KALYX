"""
Execution service for order placement and management.
"""
import logging
import asyncio
from typing import List, Dict, Any, Optional
from datetime import datetime
from sqlalchemy.orm import Session

from app.auth.service import AuthService
from app.data import models
from app.data.redis_client import get_redis

logger = logging.getLogger(__name__)


class ExecutionService:
    """Service for executing trades."""
    
    def __init__(self, db: Session):
        self.db = db
        self.auth_service = AuthService()
        self._rate_limit_delay = 0.1  # 100ms between orders (Zerodha limit)
        self._last_order_time = None
    
    async def place_order(
        self,
        tradingsymbol: str,
        exchange: str,
        transaction_type: str,
        quantity: int,
        order_type: str = "MARKET",
        product: str = "MIS",
        price: Optional[float] = None,
        trigger_price: Optional[float] = None,
        strategy_id: Optional[int] = None
    ) -> Dict:
        """Place a new order."""
        try:
            # Rate limiting
            await self._rate_limit()
            
            # Get Kite client
            kite = self.auth_service.get_kite_client()
            if not kite:
                raise RuntimeError("Kite client not initialized. Please login first.")
            
            # Prepare order parameters
            order_params = {
                "tradingsymbol": tradingsymbol,
                "exchange": exchange,
                "transaction_type": transaction_type,
                "quantity": quantity,
                "order_type": order_type,
                "product": product,
            }
            
            if price:
                order_params["price"] = price
            if trigger_price:
                order_params["trigger_price"] = trigger_price
            
            # Place order with retry logic
            order_response = await self._place_order_with_retry(kite, order_params)
            
            order_id = order_response.get("order_id")
            exchange_order_id = order_response.get("exchange_order_id", "")
            
            # Get instrument token
            instruments = kite.instruments(exchange)
            instrument_token = None
            for inst in instruments:
                if inst["tradingsymbol"] == tradingsymbol:
                    instrument_token = inst["instrument_token"]
                    break
            
            # Store in database
            trade = models.Trade(
                order_id=order_id,
                exchange_order_id=exchange_order_id,
                tradingsymbol=tradingsymbol,
                instrument_token=instrument_token,
                exchange=exchange,
                transaction_type=transaction_type,
                product=product,
                order_type=order_type,
                quantity=quantity,
                price=price,
                trigger_price=trigger_price,
                status="PENDING",
                strategy_id=strategy_id,
                order_timestamp=datetime.utcnow()
            )
            
            self.db.add(trade)
            self.db.commit()
            self.db.refresh(trade)
            
            logger.info(f"Order placed: {order_id} - {tradingsymbol} {transaction_type} {quantity}")
            
            return {
                "id": trade.id,
                "order_id": order_id,
                "tradingsymbol": tradingsymbol,
                "status": trade.status,
                "quantity": quantity,
                "filled_quantity": trade.filled_quantity,
                "average_price": trade.average_price,
                "created_at": trade.created_at.isoformat()
            }
            
        except Exception as e:
            logger.error(f"Order placement failed: {e}", exc_info=True)
            raise
    
    async def _place_order_with_retry(
        self,
        kite,
        order_params: Dict[str, Any],
        max_retries: int = 3
    ) -> Dict:
        """Place order with retry logic."""
        last_error = None
        
        for attempt in range(max_retries):
            try:
                # Place order
                order_response = kite.place_order(**order_params)
                return order_response
            except Exception as e:
                last_error = e
                if attempt < max_retries - 1:
                    wait_time = 2 ** attempt  # Exponential backoff
                    logger.warning(f"Order placement failed (attempt {attempt + 1}), retrying in {wait_time}s...")
                    await asyncio.sleep(wait_time)
                else:
                    logger.error(f"Order placement failed after {max_retries} attempts")
        
        raise last_error
    
    async def _rate_limit(self):
        """Enforce rate limiting."""
        if self._last_order_time:
            elapsed = (datetime.utcnow() - self._last_order_time).total_seconds()
            if elapsed < self._rate_limit_delay:
                await asyncio.sleep(self._rate_limit_delay - elapsed)
        
        self._last_order_time = datetime.utcnow()
    
    def get_orders(
        self,
        status: Optional[str] = None,
        strategy_id: Optional[int] = None
    ) -> List[Dict]:
        """Get orders."""
        query = self.db.query(models.Trade)
        
        if status:
            query = query.filter(models.Trade.status == status)
        if strategy_id:
            query = query.filter(models.Trade.strategy_id == strategy_id)
        
        trades = query.order_by(models.Trade.created_at.desc()).all()
        return [self._trade_to_dict(t) for t in trades]
    
    def get_order(self, order_id: str) -> Optional[Dict]:
        """Get order by ID."""
        trade = self.db.query(models.Trade).filter(
            models.Trade.order_id == order_id
        ).first()
        
        if not trade:
            return None
        
        return self._trade_to_dict(trade)
    
    async def cancel_order(self, order_id: str) -> str:
        """Cancel an order."""
        try:
            trade = self.db.query(models.Trade).filter(
                models.Trade.order_id == order_id
            ).first()
            
            if not trade:
                raise ValueError(f"Order {order_id} not found")
            
            if trade.status in ["COMPLETE", "CANCELLED", "REJECTED"]:
                raise ValueError(f"Order {order_id} cannot be cancelled (status: {trade.status})")
            
            # Get Kite client
            kite = self.auth_service.get_kite_client()
            if not kite:
                raise RuntimeError("Kite client not initialized")
            
            # Cancel order
            kite.cancel_order(variety=trade.product, order_id=order_id)
            
            # Update status
            trade.status = "CANCELLED"
            self.db.commit()
            
            logger.info(f"Order cancelled: {order_id}")
            return order_id
            
        except Exception as e:
            logger.error(f"Order cancellation failed: {e}", exc_info=True)
            raise
    
    async def get_positions(self) -> List[Dict]:
        """Get current positions from Zerodha."""
        try:
            kite = self.auth_service.get_kite_client()
            if not kite:
                raise RuntimeError("Kite client not initialized")
            
            positions = kite.positions()
            net_positions = positions.get("net", [])
            
            return [{
                "tradingsymbol": p.get("tradingsymbol"),
                "exchange": p.get("exchange"),
                "quantity": p.get("quantity"),
                "average_price": p.get("average_price"),
                "last_price": p.get("last_price"),
                "pnl": p.get("pnl"),
                "product": p.get("product")
            } for p in net_positions if p.get("quantity") != 0]
            
        except Exception as e:
            logger.error(f"Failed to fetch positions: {e}", exc_info=True)
            raise
    
    def _trade_to_dict(self, trade: models.Trade) -> Dict:
        """Convert trade model to dictionary."""
        return {
            "id": trade.id,
            "order_id": trade.order_id,
            "tradingsymbol": trade.tradingsymbol,
            "status": trade.status,
            "quantity": trade.quantity,
            "filled_quantity": trade.filled_quantity,
            "average_price": trade.average_price,
            "pnl": trade.pnl,
            "created_at": trade.created_at.isoformat() if trade.created_at else None
        }

