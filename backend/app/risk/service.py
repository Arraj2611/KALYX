"""
Risk and capital management service.
"""
import logging
from typing import Dict, Any
from datetime import datetime, date
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.brokers.base import BrokerAdapter
from app.config import settings
from app.data import models
from app.data.redis_client import get_redis

logger = logging.getLogger(__name__)


class RiskService:
    """Service for risk and capital management."""

    def __init__(self, db: Session, adapter: BrokerAdapter):
        self.db = db
        self.adapter = adapter
        self.circuit_breaker_active = False

    async def get_risk_status(self) -> Dict[str, Any]:
        """Get current risk status."""
        try:
            # Get margins
            margins = await self.get_margins()
            available_margin = margins.get("available", {}).get("cash", 0.0)
            used_margin = margins.get("utilised", {}).get("debits", 0.0)
            total_margin = available_margin + used_margin

            # Calculate capital usage percentage
            capital_usage_pct = (used_margin / total_margin * 100) if total_margin > 0 else 0.0

            # Get daily P&L
            today = date.today()
            daily_pnl = self.db.query(func.sum(models.Trade.pnl)).filter(
                func.date(models.Trade.created_at) == today
            ).scalar() or 0.0

            # Get daily trade count
            daily_trades = self.db.query(func.count(models.Trade.id)).filter(
                func.date(models.Trade.created_at) == today
            ).scalar() or 0

            # Check for breaches
            is_breach = (
                capital_usage_pct > settings.MAX_CAPITAL_USAGE_PCT or
                daily_pnl < -settings.MAX_LOSS_PER_DAY or
                daily_trades >= settings.MAX_TRADES_PER_DAY
            )

            return {
                "capital_usage_pct": round(capital_usage_pct, 2),
                "daily_pnl": round(daily_pnl, 2),
                "daily_trades": daily_trades,
                "max_capital_usage_pct": settings.MAX_CAPITAL_USAGE_PCT,
                "max_loss_per_day": settings.MAX_LOSS_PER_DAY,
                "max_trades_per_day": settings.MAX_TRADES_PER_DAY,
                "is_breach": is_breach,
                "circuit_breaker_active": self.circuit_breaker_active,
                "available_margin": round(available_margin, 2),
                "used_margin": round(used_margin, 2)
            }

        except Exception as e:
            logger.error(f"Failed to get risk status: {e}", exc_info=True)
            raise

    async def get_margins(self) -> Dict[str, Any]:
        """Get current margin details from the broker adapter."""
        try:
            margin = await self.adapter.get_margins()
            return {
                "available": {"cash": margin.available_cash},
                "utilised": {"debits": margin.used_margin}
            }
        except Exception as e:
            logger.error(f"Failed to fetch margins: {e}", exc_info=True)
            raise

    def check_risk_breach(self) -> bool:
        """Check if risk limits are breached."""
        return self.circuit_breaker_active

    def activate_circuit_breaker(self, reason: str):
        """Activate circuit breaker."""
        self.circuit_breaker_active = True
        logger.critical(f"Circuit breaker activated: {reason}")

        # Store in Redis
        redis = get_redis()
        redis.set("risk:circuit_breaker", "true")
        redis.set("risk:circuit_breaker_reason", reason)

    def reset_circuit_breaker(self):
        """Reset circuit breaker."""
        self.circuit_breaker_active = False
        logger.info("Circuit breaker reset")

        # Clear from Redis
        redis = get_redis()
        redis.delete("risk:circuit_breaker")
        redis.delete("risk:circuit_breaker_reason")

    def calculate_position_size(
        self,
        available_margin: float,
        risk_per_trade_pct: float = 2.0
    ) -> int:
        """
        Calculate position size based on available margin and risk percentage.

        Args:
            available_margin: Available margin in INR
            risk_per_trade_pct: Risk per trade as percentage of capital

        Returns:
            Suggested position size (quantity)
        """
        risk_amount = available_margin * (risk_per_trade_pct / 100)
        position_size = int(risk_amount / 1000)  # Simplified calculation
        return max(1, min(position_size, 10))  # Limit between 1 and 10 lots
