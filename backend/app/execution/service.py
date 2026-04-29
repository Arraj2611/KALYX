"""
Execution service for order placement and management.
"""
import logging
from typing import List, Dict, Any, Optional
from datetime import datetime
from sqlalchemy.orm import Session

from app.brokers.base import BrokerAdapter, UnifiedOrder
from app.data import models

logger = logging.getLogger(__name__)


class ExecutionService:
    """Service for executing trades."""

    def __init__(self, db: Session, adapter: BrokerAdapter):
        self.db = db
        self.adapter = adapter

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
            # Determine segment from exchange
            segment = "FNO" if exchange == "NFO" else "CASH"

            order = UnifiedOrder(
                symbol=tradingsymbol,
                exchange=exchange,
                segment=segment,
                transaction_type=transaction_type,
                quantity=quantity,
                order_type=order_type,
                product=product,
                price=price,
                trigger_price=trigger_price,
            )

            result = await self.adapter.place_order(order)
            order_id = result.broker_order_id

            # Store in database
            trade = models.Trade(
                order_id=order_id,
                exchange_order_id="",
                tradingsymbol=tradingsymbol,
                instrument_token=None,
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

            # Determine segment from trade exchange
            segment = "FNO" if trade.exchange == "NFO" else "CASH"

            await self.adapter.cancel_order(order_id, segment)

            # Update status
            trade.status = "CANCELLED"
            self.db.commit()

            logger.info(f"Order cancelled: {order_id}")
            return order_id

        except Exception as e:
            logger.error(f"Order cancellation failed: {e}", exc_info=True)
            raise

    async def get_positions(self) -> List[Dict]:
        """Get current positions from the broker adapter."""
        try:
            positions = await self.adapter.get_positions()

            return [{
                "tradingsymbol": p.symbol,
                "exchange": p.exchange,
                "quantity": p.quantity,
                "average_price": p.average_price,
                "last_price": p.last_price,
                "pnl": p.pnl,
                "product": p.product
            } for p in positions if p.quantity != 0]

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
