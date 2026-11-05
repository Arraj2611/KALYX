"""PaperAdapter — in-memory simulated broker for KALYX paper trading.

Fills orders immediately with configurable slippage, tracks positions and
margin in memory, and satisfies the full BrokerAdapter interface so
strategies can run against it without touching a real broker.
"""

from __future__ import annotations

import logging
import random
import string
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Optional

from app.brokers.base import (
    AuthResult,
    AuthStatus,
    BrokerAdapter,
    Holding,
    Instrument,
    MarginInfo,
    OrderResult,
    OrderStatus,
    Position,
    Quote,
    RateLimitConfig,
    TickCallback,
    UnifiedOrder,
)


logger = logging.getLogger(__name__)

# async (symbols) -> {symbol: last traded price}; symbols it cannot price are left out
PriceSource = Callable[[list[str]], Awaitable[dict[str, float]]]


def _generate_order_id() -> str:
    """Generate a unique PAPER-XXXXXX order identifier."""
    suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
    return f"PAPER-{suffix}"


class PaperAdapter(BrokerAdapter):
    """Simulated broker adapter for paper trading.

    Parameters
    ----------
    config : dict
        ``initial_capital``  — starting cash (default 1 000 000).
        ``slippage_pct``     — one-way slippage as a percentage (default 0.05,
                               meaning 0.05 % per side).
    price_source : optional
        Async callable giving live prices. With it, market orders fill at the market
        price (not the price the caller guessed), ``get_ltp`` is live and open
        positions are marked to market. Without it, behaviour is unchanged.
    """

    def __init__(
        self,
        config: Optional[dict[str, Any]] = None,
        price_source: Optional[PriceSource] = None,
    ) -> None:
        cfg = config or {}
        self._price_source = price_source
        self._initial_capital: float = float(cfg.get("initial_capital", 1_000_000))
        self._slippage_pct: float = float(cfg.get("slippage_pct", 0.05))

        self._logged_in: bool = False
        self._user_id: str = "paper_user"

        # order_id -> OrderStatus
        self._orders: dict[str, OrderStatus] = {}

        # symbol -> Position  (positions with qty == 0 are kept but filtered on read)
        self._positions: dict[str, Position] = {}

        # Total value of open positions (used_margin)
        self._used_margin: float = 0.0

    # ------------------------------------------------------------------
    # Identity & capability properties
    # ------------------------------------------------------------------

    @property
    def name(self) -> str:
        return "paper"

    @property
    def supported_segments(self) -> list[str]:
        return ["CASH", "FNO", "COMMODITY", "SPOT", "FUTURES"]

    @property
    def rate_limits(self) -> RateLimitConfig:
        return RateLimitConfig(
            orders_per_second=100,
            orders_per_minute=6_000,
            data_requests_per_second=200,
            max_ws_subscriptions=10_000,
        )

    @property
    def is_connected(self) -> bool:
        return self._logged_in

    # ------------------------------------------------------------------
    # Authentication
    # ------------------------------------------------------------------

    async def login(self, credentials: dict[str, Any]) -> AuthResult:
        self._logged_in = True
        return AuthResult(
            success=True,
            user_id=self._user_id,
            broker_name=self.name,
            message="Paper trading session started.",
        )

    async def logout(self) -> None:
        self._logged_in = False

    async def get_auth_status(self) -> AuthStatus:
        return AuthStatus(
            is_valid=self._logged_in,
            user_id=self._user_id if self._logged_in else "",
            broker_name=self.name,
            expires_at=None,
        )

    # ------------------------------------------------------------------
    # Order management
    # ------------------------------------------------------------------

    async def place_order(self, order: UnifiedOrder) -> OrderResult:
        """Fill immediately at price ± slippage; update positions and margin."""
        market = await self._market_prices([order.symbol])
        raw_price = market.get(order.symbol) or order.price or 0.0
        if raw_price <= 0:
            from app.brokers.base import OrderRejectedError

            raise OrderRejectedError(self.name, f"No price for {order.symbol}; paper will not fill at zero.")
        slip_factor = self._slippage_pct / 100.0

        if order.transaction_type == "BUY":
            fill_price = raw_price * (1 + slip_factor)
        else:
            fill_price = raw_price * (1 - slip_factor)

        order_id = _generate_order_id()

        order_status = OrderStatus(
            broker_order_id=order_id,
            symbol=order.symbol,
            status="COMPLETE",
            quantity=order.quantity,
            filled_quantity=order.quantity,
            average_price=fill_price,
            order_type=order.order_type,
            transaction_type=order.transaction_type,
            broker_name=self.name,
        )
        self._orders[order_id] = order_status

        # Update positions
        self._update_position(order, fill_price)

        return OrderResult(
            broker_order_id=order_id,
            status="COMPLETE",
            broker_name=self.name,
            raw_response={
                "order_id": order_id,
                "fill_price": fill_price,
                "quantity": order.quantity,
                "transaction_type": order.transaction_type,
            },
        )

    async def modify_order(
        self, order_id: str, changes: dict[str, Any]
    ) -> OrderResult:
        """Paper orders are already filled; modification is a no-op."""
        existing = self._orders.get(order_id)
        if existing is None:
            from app.brokers.base import OrderRejectedError
            raise OrderRejectedError(self.name, f"Order {order_id} not found.")
        return OrderResult(
            broker_order_id=order_id,
            status=existing.status,
            broker_name=self.name,
            raw_response={"order_id": order_id, "modified": False},
        )

    async def cancel_order(self, order_id: str, segment: str) -> str:
        """Paper fills are instant; cancellation is a no-op returning the id."""
        return order_id

    async def get_order_status(self, order_id: str) -> OrderStatus:
        if order_id not in self._orders:
            from app.brokers.base import OrderRejectedError
            raise OrderRejectedError(self.name, f"Order {order_id} not found.")
        return self._orders[order_id]

    async def get_orders(self) -> list[OrderStatus]:
        return list(self._orders.values())

    # ------------------------------------------------------------------
    # Portfolio
    # ------------------------------------------------------------------

    async def get_positions(self) -> list[Position]:
        """Return positions with non-zero quantity, marked to market when a price source exists."""
        open_positions = [p for p in self._positions.values() if p.quantity != 0]
        live = await self._market_prices([p.symbol for p in open_positions])
        for position in open_positions:
            price = live.get(position.symbol)
            if price:
                position.last_price = price
                position.pnl = (price - position.average_price) * position.quantity
        return [replace(position) for position in open_positions]  # snapshots, not live objects

    async def get_holdings(self) -> list[Holding]:
        """Paper trading has no demat holdings."""
        return []

    async def get_margins(self) -> MarginInfo:
        available = self._initial_capital - self._used_margin
        return MarginInfo(
            available_cash=available,
            used_margin=self._used_margin,
            total_margin=self._initial_capital,
            broker_name=self.name,
            raw={},
        )

    # ------------------------------------------------------------------
    # Market data — minimal stubs (paper adapter is order/portfolio focused)
    # ------------------------------------------------------------------

    async def get_ltp(self, symbols: list[str]) -> dict[str, float]:
        # Live price when a source is configured, else the last price seen for the position, else 0
        live = await self._market_prices(symbols)
        if self._price_source is not None:
            # 0.0 means no price. Falling back to the last fill would hide a dead feed from every stop check.
            return {sym: live.get(sym, 0.0) for sym in symbols}
        return {sym: self._positions[sym].last_price if sym in self._positions else 0.0 for sym in symbols}

    async def get_quote(
        self, symbol: str, exchange: str, segment: str
    ) -> Quote:
        ltp = self._positions[symbol].average_price if symbol in self._positions else 0.0
        return Quote(
            symbol=symbol,
            exchange=exchange,
            ltp=ltp,
            open=ltp,
            high=ltp,
            low=ltp,
            close=ltp,
            volume=0,
            broker_name=self.name,
        )

    async def get_instruments(
        self, exchange: Optional[str] = None
    ) -> list[Instrument]:
        return []

    # ------------------------------------------------------------------
    # Live feed — no-ops for paper trading
    # ------------------------------------------------------------------

    async def subscribe_ticks(
        self, symbols: list[str], callback: TickCallback
    ) -> None:
        pass

    async def unsubscribe_ticks(self, symbols: list[str]) -> None:
        pass

    async def disconnect_feed(self) -> None:
        self._logged_in = False

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _market_prices(self, symbols: list[str]) -> dict[str, float]:
        """Live prices for the symbols; empty when there is no source or it fails."""
        if self._price_source is None or not symbols:
            return {}
        try:
            prices = await self._price_source(list(symbols))
        except Exception as exc:
            logger.warning("Paper price source failed: %s", exc)
            return {}
        return {sym: price for sym, price in prices.items() if price and price > 0}

    def _update_position(self, order: UnifiedOrder, fill_price: float) -> None:
        """Update in-memory position and margin accounting."""
        sym = order.symbol
        qty = order.quantity
        trade_value = fill_price * qty

        if sym not in self._positions:
            # First trade in this symbol — create a blank position
            self._positions[sym] = Position(
                symbol=sym,
                exchange=order.exchange,
                segment=order.segment,
                quantity=0,
                average_price=0.0,
                last_price=fill_price,
                pnl=0.0,
                product=order.product,
                broker_name=self.name,
            )

        pos = self._positions[sym]

        if order.transaction_type == "BUY":
            # Weighted average price for multiple buys
            new_qty = pos.quantity + qty
            if new_qty > 0:
                pos.average_price = (
                    (pos.average_price * pos.quantity) + (fill_price * qty)
                ) / new_qty
            pos.quantity = new_qty
            # Charge margin
            self._used_margin += trade_value

        else:  # SELL
            new_qty = pos.quantity - qty
            if new_qty <= 0:
                # Position fully closed or reversed — release all margin
                self._used_margin -= pos.average_price * pos.quantity
                if new_qty < 0:
                    # Short position opened
                    pos.average_price = fill_price
                    self._used_margin += fill_price * abs(new_qty)
                else:
                    pos.average_price = 0.0
            else:
                # Partial close — release proportional margin
                self._used_margin -= pos.average_price * qty
            pos.quantity = new_qty

        pos.last_price = fill_price
        pos.pnl = (pos.last_price - pos.average_price) * pos.quantity

        # Guard against floating-point drift below zero
        self._used_margin = max(0.0, self._used_margin)
