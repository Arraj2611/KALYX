"""Broker abstraction layer — public API.

Import everything from this package rather than from base.py directly.
"""

from app.brokers.base import (
    # Type aliases
    TickCallback,
    # Error hierarchy
    BrokerError,
    AuthenticationError,
    OrderRejectedError,
    RateLimitError,
    InsufficientMarginError,
    BrokerUnavailableError,
    InvalidSymbolError,
    # Dataclasses
    TradeContext,
    UnifiedOrder,
    OrderResult,
    OrderStatus,
    Position,
    Holding,
    MarginInfo,
    Quote,
    Instrument,
    AuthResult,
    AuthStatus,
    RateLimitConfig,
    # ABC
    BrokerAdapter,
)

__all__ = [
    "TickCallback",
    "BrokerError",
    "AuthenticationError",
    "OrderRejectedError",
    "RateLimitError",
    "InsufficientMarginError",
    "BrokerUnavailableError",
    "InvalidSymbolError",
    "TradeContext",
    "UnifiedOrder",
    "OrderResult",
    "OrderStatus",
    "Position",
    "Holding",
    "MarginInfo",
    "Quote",
    "Instrument",
    "AuthResult",
    "AuthStatus",
    "RateLimitConfig",
    "BrokerAdapter",
]
