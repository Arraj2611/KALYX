"""Generic conformance tests for BrokerAdapter implementations.

Parameterized over ADAPTER_FACTORIES so every adapter added to that list is
automatically verified against the full contract. New adapters only need to
provide a factory function — all 13 tests run for free.
"""

from __future__ import annotations

import pytest

from app.brokers.base import (
    AuthResult,
    AuthStatus,
    BrokerAdapter,
    Holding,
    MarginInfo,
    OrderResult,
    OrderStatus,
    Position,
    RateLimitConfig,
    UnifiedOrder,
)


# ---------------------------------------------------------------------------
# Adapter factories — add new adapters here
# ---------------------------------------------------------------------------


def make_paper_adapter():
    from app.brokers.paper.adapter import PaperAdapter

    return PaperAdapter(config={"initial_capital": 500000, "slippage_pct": 0.0})


def make_zerodha_adapter():
    from unittest.mock import MagicMock

    from app.brokers.zerodha.adapter import ZerodhaAdapter

    mock_kite = MagicMock()
    mock_kite.generate_session.return_value = {"access_token": "t", "user_id": "U"}
    mock_kite.profile.return_value = {"user_id": "U"}
    mock_kite.place_order.return_value = {"order_id": "Z1"}
    mock_kite.positions.return_value = {"net": []}
    mock_kite.margins.return_value = {
        "equity": {"available": {"cash": 100000}, "utilised": {"debits": 0}}
    }
    mock_kite.orders.return_value = []
    mock_kite.holdings.return_value = []
    mock_kite.ltp.return_value = {}

    adapter = ZerodhaAdapter(api_key="k", api_secret="s")
    adapter._kite = mock_kite
    adapter._logged_in = True
    return adapter


ADAPTER_FACTORIES = [
    pytest.param(make_paper_adapter, id="paper"),
    pytest.param(make_zerodha_adapter, id="zerodha"),
]


# ---------------------------------------------------------------------------
# Shared fixture
# ---------------------------------------------------------------------------


@pytest.fixture(params=ADAPTER_FACTORIES)
def adapter(request):
    """Instantiate one adapter per factory for every conformance test."""
    factory = request.param
    return factory()


# ---------------------------------------------------------------------------
# Conformance tests
# ---------------------------------------------------------------------------


def test_conformance_is_broker_adapter(adapter):
    """Every adapter must be an instance of BrokerAdapter."""
    assert isinstance(adapter, BrokerAdapter)


def test_conformance_name_is_string(adapter):
    """adapter.name must be a non-empty string."""
    assert isinstance(adapter.name, str)
    assert len(adapter.name) > 0


def test_conformance_segments_is_list(adapter):
    """adapter.supported_segments must be a non-empty list of strings."""
    segs = adapter.supported_segments
    assert isinstance(segs, list)
    assert len(segs) > 0
    for seg in segs:
        assert isinstance(seg, str)


def test_conformance_rate_limits(adapter):
    """adapter.rate_limits must return a RateLimitConfig with orders_per_second > 0."""
    rl = adapter.rate_limits
    assert isinstance(rl, RateLimitConfig)
    assert rl.orders_per_second > 0


@pytest.mark.asyncio
async def test_conformance_login_returns_auth_result(adapter):
    """login({}) must return AuthResult whose broker_name matches adapter.name."""
    result = await adapter.login({})
    assert isinstance(result, AuthResult)
    assert result.broker_name == adapter.name


@pytest.mark.asyncio
async def test_conformance_auth_status_after_login(adapter):
    """After login, get_auth_status() must return is_valid=True with matching broker_name."""
    await adapter.login({})
    status = await adapter.get_auth_status()
    assert isinstance(status, AuthStatus)
    assert status.is_valid is True
    assert status.broker_name == adapter.name


@pytest.mark.asyncio
async def test_conformance_place_order_returns_order_result(adapter):
    """place_order with a LIMIT BUY must return OrderResult with non-empty broker_order_id."""
    await adapter.login({})
    order = UnifiedOrder(
        symbol="RELIANCE",
        exchange="NSE",
        segment="CASH",
        transaction_type="BUY",
        quantity=1,
        order_type="LIMIT",
        product="MIS",
        price=2500.0,
    )
    result = await adapter.place_order(order)
    assert isinstance(result, OrderResult)
    assert isinstance(result.broker_order_id, str)
    assert len(result.broker_order_id) > 0
    assert result.broker_name == adapter.name


@pytest.mark.asyncio
async def test_conformance_get_orders_returns_list(adapter):
    """get_orders() must return a list; each element must be an OrderStatus."""
    await adapter.login({})
    order = UnifiedOrder(
        symbol="INFY",
        exchange="NSE",
        segment="CASH",
        transaction_type="BUY",
        quantity=1,
        order_type="LIMIT",
        product="MIS",
        price=1500.0,
    )
    await adapter.place_order(order)
    orders = await adapter.get_orders()
    assert isinstance(orders, list)
    for o in orders:
        assert isinstance(o, OrderStatus)


@pytest.mark.asyncio
async def test_conformance_get_positions_returns_list(adapter):
    """get_positions() must return a list; each element must be a Position."""
    await adapter.login({})
    positions = await adapter.get_positions()
    assert isinstance(positions, list)
    for p in positions:
        assert isinstance(p, Position)


@pytest.mark.asyncio
async def test_conformance_get_holdings_returns_list(adapter):
    """get_holdings() must return a list; each element must be a Holding."""
    await adapter.login({})
    holdings = await adapter.get_holdings()
    assert isinstance(holdings, list)
    for h in holdings:
        assert isinstance(h, Holding)


@pytest.mark.asyncio
async def test_conformance_get_margins_returns_margin_info(adapter):
    """get_margins() must return MarginInfo with matching broker_name and total_margin >= 0."""
    await adapter.login({})
    margin = await adapter.get_margins()
    assert isinstance(margin, MarginInfo)
    assert margin.broker_name == adapter.name
    assert margin.total_margin >= 0


@pytest.mark.asyncio
async def test_conformance_get_ltp_returns_dict(adapter):
    """get_ltp([symbol]) must return a dict."""
    await adapter.login({})
    result = await adapter.get_ltp(["RELIANCE"])
    assert isinstance(result, dict)


@pytest.mark.asyncio
async def test_conformance_logout(adapter):
    """After logout(), get_auth_status() must return is_valid=False."""
    await adapter.login({})
    await adapter.logout()
    status = await adapter.get_auth_status()
    assert isinstance(status, AuthStatus)
    assert status.is_valid is False
