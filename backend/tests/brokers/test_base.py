"""Tests for BrokerAdapter ABC, unified data models, and error types."""

import pytest
from datetime import datetime

from app.brokers.base import (
    # Error types
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


# ---------------------------------------------------------------------------
# Dataclass tests
# ---------------------------------------------------------------------------


def test_unified_order_creation():
    """Create UnifiedOrder with TradeContext and verify all fields."""
    context = TradeContext(
        strategy_id="momentum_v1",
        account_name="zerodha_main",
        signals={"rsi": 72.5, "macd_cross": True},
        market_state={"vix": 14.2, "trend": "bullish"},
        reasoning="RSI overbought, MACD bullish crossover detected",
        confidence=0.85,
        timestamp=datetime(2026, 4, 29, 10, 30, 0),
    )

    order = UnifiedOrder(
        symbol="RELIANCE",
        exchange="NSE",
        segment="EQ",
        transaction_type="BUY",
        quantity=10,
        order_type="MARKET",
        product="CNC",
        context=context,
    )

    assert order.symbol == "RELIANCE"
    assert order.exchange == "NSE"
    assert order.segment == "EQ"
    assert order.transaction_type == "BUY"
    assert order.quantity == 10
    assert order.order_type == "MARKET"
    assert order.product == "CNC"
    assert order.price is None
    assert order.trigger_price is None
    assert order.context is context
    assert order.context.strategy_id == "momentum_v1"
    assert order.context.confidence == 0.85


def test_unified_order_with_limit_price():
    """Verify price and trigger_price fields on UnifiedOrder."""
    order = UnifiedOrder(
        symbol="INFY",
        exchange="NSE",
        segment="EQ",
        transaction_type="SELL",
        quantity=5,
        order_type="SL",
        product="MIS",
        price=1500.50,
        trigger_price=1498.00,
    )

    assert order.price == 1500.50
    assert order.trigger_price == 1498.00
    assert order.context is None


def test_position_dataclass():
    """Create Position and verify broker_name field."""
    position = Position(
        symbol="NIFTY23DECFUT",
        exchange="NFO",
        segment="FUT",
        quantity=50,
        average_price=19500.0,
        last_price=19620.0,
        pnl=6000.0,
        product="NRML",
        broker_name="zerodha",
    )

    assert position.symbol == "NIFTY23DECFUT"
    assert position.broker_name == "zerodha"
    assert position.pnl == 6000.0
    assert position.quantity == 50


def test_margin_info_dataclass():
    """Create MarginInfo with raw dict and verify fields."""
    raw = {"equity": {"available": {"cash": 50000.0}}}
    margin = MarginInfo(
        available_cash=50000.0,
        used_margin=15000.0,
        total_margin=65000.0,
        broker_name="zerodha",
        raw=raw,
    )

    assert margin.available_cash == 50000.0
    assert margin.used_margin == 15000.0
    assert margin.total_margin == 65000.0
    assert margin.broker_name == "zerodha"
    assert margin.raw == raw


def test_order_result_dataclass():
    """Verify OrderResult fields."""
    raw = {"order_id": "ABC123", "status": "open"}
    result = OrderResult(
        broker_order_id="ABC123",
        status="OPEN",
        broker_name="zerodha",
        raw_response=raw,
    )

    assert result.broker_order_id == "ABC123"
    assert result.status == "OPEN"
    assert result.broker_name == "zerodha"
    assert result.raw_response == raw


def test_auth_result_dataclass():
    """Verify AuthResult fields."""
    auth = AuthResult(
        success=True,
        user_id="user123",
        broker_name="zerodha",
        message="Login successful",
    )

    assert auth.success is True
    assert auth.user_id == "user123"
    assert auth.broker_name == "zerodha"
    assert auth.message == "Login successful"


def test_rate_limit_config():
    """Verify RateLimitConfig fields."""
    config = RateLimitConfig(
        orders_per_second=10,
        orders_per_minute=200,
        data_requests_per_second=5,
        max_ws_subscriptions=3000,
    )

    assert config.orders_per_second == 10
    assert config.orders_per_minute == 200
    assert config.data_requests_per_second == 5
    assert config.max_ws_subscriptions == 3000


def test_quote_dataclass():
    """Quote with optional oi field — oi defaults to None."""
    quote = Quote(
        symbol="RELIANCE",
        exchange="NSE",
        ltp=2500.0,
        open=2480.0,
        high=2520.0,
        low=2470.0,
        close=2490.0,
        volume=1500000,
        broker_name="zerodha",
    )

    assert quote.symbol == "RELIANCE"
    assert quote.ltp == 2500.0
    assert quote.oi is None
    assert quote.bid is None
    assert quote.ask is None
    assert quote.broker_name == "zerodha"

    # With oi set
    quote_with_oi = Quote(
        symbol="NIFTY23DECFUT",
        exchange="NFO",
        ltp=19500.0,
        open=19400.0,
        high=19600.0,
        low=19380.0,
        close=19450.0,
        volume=500000,
        oi=1200000,
        broker_name="zerodha",
    )
    assert quote_with_oi.oi == 1200000


def test_instrument_dataclass():
    """Instrument with expiry and strike fields."""
    # Equity instrument
    equity = Instrument(
        symbol="RELIANCE",
        exchange="NSE",
        segment="EQ",
        instrument_type="EQ",
        lot_size=1,
        tick_size=0.05,
        broker_name="zerodha",
    )

    assert equity.symbol == "RELIANCE"
    assert equity.expiry is None
    assert equity.strike is None
    assert equity.lot_size == 1

    # Options instrument
    option = Instrument(
        symbol="NIFTY23DEC19500CE",
        exchange="NFO",
        segment="OPT",
        instrument_type="CE",
        lot_size=50,
        tick_size=0.05,
        expiry="2023-12-28",
        strike=19500.0,
        broker_name="zerodha",
    )

    assert option.expiry == "2023-12-28"
    assert option.strike == 19500.0
    assert option.lot_size == 50


# ---------------------------------------------------------------------------
# Error hierarchy tests
# ---------------------------------------------------------------------------


def test_broker_error_hierarchy():
    """All broker errors are subclasses of BrokerError with broker_name and message."""
    error_types = [
        AuthenticationError,
        OrderRejectedError,
        RateLimitError,
        InsufficientMarginError,
        BrokerUnavailableError,
        InvalidSymbolError,
    ]

    for ErrorClass in error_types:
        assert issubclass(ErrorClass, BrokerError), (
            f"{ErrorClass.__name__} must be a subclass of BrokerError"
        )
        assert issubclass(ErrorClass, Exception), (
            f"{ErrorClass.__name__} must be a subclass of Exception"
        )

        err = ErrorClass(broker_name="zerodha", message=f"test {ErrorClass.__name__}")
        assert err.broker_name == "zerodha"
        assert f"test {ErrorClass.__name__}" in str(err)

    # BrokerError itself is also an Exception
    assert issubclass(BrokerError, Exception)

    # With optional original_error
    original = ValueError("network timeout")
    err = AuthenticationError(
        broker_name="groww",
        message="Session expired",
        original_error=original,
    )
    assert err.broker_name == "groww"
    assert err.original_error is original


# ---------------------------------------------------------------------------
# ABC test
# ---------------------------------------------------------------------------


def test_broker_adapter_is_abstract():
    """Instantiating BrokerAdapter directly raises TypeError."""
    with pytest.raises(TypeError):
        BrokerAdapter()
