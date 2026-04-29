"""
BrokerAdapter abstract base class, unified data models, and error types.

Foundation for multi-broker support in KALYX. All broker implementations
must subclass BrokerAdapter and implement its abstract interface.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Optional


# ---------------------------------------------------------------------------
# Type aliases
# ---------------------------------------------------------------------------

TickCallback = Callable[[dict], None]


# ---------------------------------------------------------------------------
# Error hierarchy
# ---------------------------------------------------------------------------


class BrokerError(Exception):
    """Base class for all broker-related errors."""

    def __init__(
        self,
        broker_name: str,
        message: str,
        original_error: Optional[Exception] = None,
    ) -> None:
        self.broker_name = broker_name
        self.message = message
        self.original_error = original_error
        super().__init__(f"[{broker_name}] {message}")


class AuthenticationError(BrokerError):
    """Raised when authentication or session validation fails."""


class OrderRejectedError(BrokerError):
    """Raised when a broker rejects an order."""


class RateLimitError(BrokerError):
    """Raised when the broker's rate limit is exceeded."""


class InsufficientMarginError(BrokerError):
    """Raised when the account has insufficient margin for an order."""


class BrokerUnavailableError(BrokerError):
    """Raised when the broker API is unreachable or returns a server error."""


class InvalidSymbolError(BrokerError):
    """Raised when a symbol is not recognized by the broker."""


# ---------------------------------------------------------------------------
# Dataclasses — context & orders
# ---------------------------------------------------------------------------


@dataclass
class TradeContext:
    """Metadata attached to each order for the learning system to consume.

    Every order carries context so KALYX can log *why* the trade was placed,
    enabling post-trade attribution and model improvement.
    """

    strategy_id: str
    account_name: str
    signals: dict[str, Any]
    market_state: dict[str, Any]
    reasoning: str
    confidence: float
    timestamp: datetime


@dataclass
class UnifiedOrder:
    """Broker-agnostic order specification.

    Translated by each BrokerAdapter implementation into the broker's
    native order format.
    """

    symbol: str
    exchange: str
    segment: str
    transaction_type: str  # "BUY" | "SELL"
    quantity: int
    order_type: str        # "MARKET" | "LIMIT" | "SL" | "SL-M"
    product: str           # "CNC" | "MIS" | "NRML" etc.
    price: Optional[float] = None
    trigger_price: Optional[float] = None
    context: Optional[TradeContext] = None


# ---------------------------------------------------------------------------
# Dataclasses — order lifecycle
# ---------------------------------------------------------------------------


@dataclass
class OrderResult:
    """Returned immediately after placing or modifying an order."""

    broker_order_id: str
    status: str
    broker_name: str
    raw_response: dict[str, Any]


@dataclass
class OrderStatus:
    """Full status of an order as returned by the broker."""

    broker_order_id: str
    symbol: str
    status: str
    quantity: int
    filled_quantity: int
    average_price: float
    order_type: str
    transaction_type: str
    broker_name: str


# ---------------------------------------------------------------------------
# Dataclasses — portfolio
# ---------------------------------------------------------------------------


@dataclass
class Position:
    """Open intraday or carry-forward position."""

    symbol: str
    exchange: str
    segment: str
    quantity: int
    average_price: float
    last_price: float
    pnl: float
    product: str
    broker_name: str


@dataclass
class Holding:
    """Long-term equity holding (demat)."""

    symbol: str
    isin: str
    quantity: int
    average_price: float
    last_price: float
    pnl: float
    broker_name: str


@dataclass
class MarginInfo:
    """Account margin summary."""

    available_cash: float
    used_margin: float
    total_margin: float
    broker_name: str
    raw: dict[str, Any]


# ---------------------------------------------------------------------------
# Dataclasses — market data
# ---------------------------------------------------------------------------


@dataclass
class Quote:
    """Full market quote for a single instrument."""

    symbol: str
    exchange: str
    ltp: float
    open: float
    high: float
    low: float
    close: float
    volume: int
    broker_name: str
    bid: Optional[float] = None
    ask: Optional[float] = None
    oi: Optional[int] = None


@dataclass
class Instrument:
    """Instrument master record."""

    symbol: str
    exchange: str
    segment: str
    instrument_type: str
    lot_size: int
    tick_size: float
    broker_name: str
    expiry: Optional[str] = None
    strike: Optional[float] = None


# ---------------------------------------------------------------------------
# Dataclasses — auth
# ---------------------------------------------------------------------------


@dataclass
class AuthResult:
    """Result returned from a login attempt."""

    success: bool
    user_id: str
    broker_name: str
    message: str


@dataclass
class AuthStatus:
    """Current authentication state for a broker session."""

    is_valid: bool
    user_id: str
    broker_name: str
    expires_at: Optional[datetime]


# ---------------------------------------------------------------------------
# Dataclasses — rate limits
# ---------------------------------------------------------------------------


@dataclass
class RateLimitConfig:
    """Per-broker rate-limit parameters consumed by the order router."""

    orders_per_second: int
    orders_per_minute: int
    data_requests_per_second: int
    max_ws_subscriptions: int


# ---------------------------------------------------------------------------
# BrokerAdapter abstract base class
# ---------------------------------------------------------------------------


class BrokerAdapter(abc.ABC):
    """Abstract interface every broker integration must implement.

    The adapter pattern decouples KALYX's trading logic from any specific
    broker API, enabling seamless switching and multi-broker execution.

    All methods are async so they can be awaited in the event loop without
    blocking the scheduler or feed handler.
    """

    # ------------------------------------------------------------------
    # Identity & capability properties
    # ------------------------------------------------------------------

    @property
    @abc.abstractmethod
    def name(self) -> str:
        """Human-readable broker identifier (e.g. 'zerodha', 'binance')."""

    @property
    @abc.abstractmethod
    def supported_segments(self) -> list[str]:
        """List of segments this broker supports (e.g. ['EQ', 'FUT', 'OPT'])."""

    @property
    @abc.abstractmethod
    def rate_limits(self) -> RateLimitConfig:
        """Rate-limit parameters for this broker."""

    @property
    @abc.abstractmethod
    def is_connected(self) -> bool:
        """True when an active authenticated session exists."""

    # ------------------------------------------------------------------
    # Authentication
    # ------------------------------------------------------------------

    @abc.abstractmethod
    async def login(self, credentials: dict[str, Any]) -> AuthResult:
        """Authenticate with the broker using the provided credentials."""

    @abc.abstractmethod
    async def logout(self) -> None:
        """Invalidate the current session."""

    @abc.abstractmethod
    async def get_auth_status(self) -> AuthStatus:
        """Return current authentication validity and expiry."""

    # ------------------------------------------------------------------
    # Order management
    # ------------------------------------------------------------------

    @abc.abstractmethod
    async def place_order(self, order: UnifiedOrder) -> OrderResult:
        """Submit a new order to the broker."""

    @abc.abstractmethod
    async def modify_order(
        self, order_id: str, changes: dict[str, Any]
    ) -> OrderResult:
        """Modify an existing open order."""

    @abc.abstractmethod
    async def cancel_order(self, order_id: str, segment: str) -> str:
        """Cancel an open order. Returns the cancelled order ID."""

    @abc.abstractmethod
    async def get_order_status(self, order_id: str) -> OrderStatus:
        """Fetch the current status of a specific order."""

    @abc.abstractmethod
    async def get_orders(self) -> list[OrderStatus]:
        """Return all orders for the current trading day."""

    # ------------------------------------------------------------------
    # Portfolio
    # ------------------------------------------------------------------

    @abc.abstractmethod
    async def get_positions(self) -> list[Position]:
        """Return all open positions."""

    @abc.abstractmethod
    async def get_holdings(self) -> list[Holding]:
        """Return demat holdings."""

    @abc.abstractmethod
    async def get_margins(self) -> MarginInfo:
        """Return current margin utilisation."""

    # ------------------------------------------------------------------
    # Market data
    # ------------------------------------------------------------------

    @abc.abstractmethod
    async def get_ltp(self, symbols: list[str]) -> dict[str, float]:
        """Return last-traded price for a list of symbols."""

    @abc.abstractmethod
    async def get_quote(
        self, symbol: str, exchange: str, segment: str
    ) -> Quote:
        """Return a full quote for a single instrument."""

    @abc.abstractmethod
    async def get_instruments(
        self, exchange: Optional[str] = None
    ) -> list[Instrument]:
        """Return the instrument master. Optionally filter by exchange."""

    # ------------------------------------------------------------------
    # Live feed
    # ------------------------------------------------------------------

    @abc.abstractmethod
    async def subscribe_ticks(
        self, symbols: list[str], callback: TickCallback
    ) -> None:
        """Subscribe to live tick data. Calls callback with each tick dict."""

    @abc.abstractmethod
    async def unsubscribe_ticks(self, symbols: list[str]) -> None:
        """Stop receiving ticks for the given symbols."""

    @abc.abstractmethod
    async def disconnect_feed(self) -> None:
        """Close the WebSocket / streaming connection."""
