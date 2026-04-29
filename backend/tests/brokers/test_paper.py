"""Tests for PaperAdapter — simulated broker for paper trading."""

import pytest
import pytest_asyncio

from app.brokers.base import (
    BrokerAdapter,
    UnifiedOrder,
)
from app.brokers.paper import PaperAdapter


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def adapter():
    """A fresh PaperAdapter with default config (1 000 000 capital, 0.05% slippage)."""
    return PaperAdapter(config={"initial_capital": 1_000_000, "slippage_pct": 0.05})


@pytest.fixture
def sample_order():
    """A simple MARKET BUY order for RELIANCE."""
    return UnifiedOrder(
        symbol="RELIANCE",
        exchange="NSE",
        segment="CASH",
        transaction_type="BUY",
        quantity=10,
        order_type="MARKET",
        product="MIS",
        price=2500.0,
    )


# ---------------------------------------------------------------------------
# Identity & capability tests (synchronous)
# ---------------------------------------------------------------------------


def test_paper_adapter_is_broker_adapter(adapter):
    assert isinstance(adapter, BrokerAdapter)


def test_paper_adapter_name(adapter):
    assert adapter.name == "paper"


def test_paper_adapter_supported_segments(adapter):
    segs = adapter.supported_segments
    assert "CASH" in segs
    assert "FNO" in segs


def test_paper_adapter_rate_limits(adapter):
    rl = adapter.rate_limits
    assert rl.orders_per_second > 0


# ---------------------------------------------------------------------------
# Auth tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_paper_auth_status_before_login(adapter):
    status = await adapter.get_auth_status()
    assert status.is_valid is False


@pytest.mark.asyncio
async def test_paper_login(adapter):
    result = await adapter.login(credentials={})
    assert result.success is True
    assert result.broker_name == "paper"


@pytest.mark.asyncio
async def test_paper_auth_status(adapter):
    assert adapter.is_connected is False
    await adapter.login(credentials={})
    assert adapter.is_connected is True


# ---------------------------------------------------------------------------
# Order tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_paper_place_order(adapter, sample_order):
    await adapter.login(credentials={})
    result = await adapter.place_order(sample_order)
    assert result is not None
    assert result.status == "COMPLETE"
    assert result.broker_order_id.startswith("PAPER-")
    assert result.broker_name == "paper"


@pytest.mark.asyncio
async def test_paper_get_orders(adapter, sample_order):
    await adapter.login(credentials={})
    await adapter.place_order(sample_order)
    orders = await adapter.get_orders()
    assert len(orders) == 1


@pytest.mark.asyncio
async def test_paper_cancel_order(adapter, sample_order):
    await adapter.login(credentials={})
    result = await adapter.place_order(sample_order)
    cancelled = await adapter.cancel_order(result.broker_order_id, "CASH")
    assert cancelled == result.broker_order_id


@pytest.mark.asyncio
async def test_paper_get_order_status(adapter, sample_order):
    await adapter.login(credentials={})
    result = await adapter.place_order(sample_order)
    status = await adapter.get_order_status(result.broker_order_id)
    assert status.broker_order_id == result.broker_order_id
    assert status.symbol == sample_order.symbol


# ---------------------------------------------------------------------------
# Slippage tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_paper_slippage_applied(adapter):
    """BUY at 2500 with 0.05% slippage → fill price 2501.25."""
    await adapter.login(credentials={})
    order = UnifiedOrder(
        symbol="INFY",
        exchange="NSE",
        segment="CASH",
        transaction_type="BUY",
        quantity=1,
        order_type="MARKET",
        product="MIS",
        price=2500.0,
    )
    await adapter.place_order(order)
    orders = await adapter.get_orders()
    assert len(orders) == 1
    assert abs(orders[0].average_price - 2501.25) < 0.001


@pytest.mark.asyncio
async def test_paper_sell_slippage(adapter):
    """SELL reduces position; after buy+sell at same qty position qty = 0."""
    await adapter.login(credentials={})
    buy = UnifiedOrder(
        symbol="TCS",
        exchange="NSE",
        segment="CASH",
        transaction_type="BUY",
        quantity=5,
        order_type="MARKET",
        product="MIS",
        price=3500.0,
    )
    sell = UnifiedOrder(
        symbol="TCS",
        exchange="NSE",
        segment="CASH",
        transaction_type="SELL",
        quantity=5,
        order_type="MARKET",
        product="MIS",
        price=3500.0,
    )
    await adapter.place_order(buy)
    await adapter.place_order(sell)
    # Position should be flat (qty == 0 so not returned)
    positions = await adapter.get_positions()
    tcs = [p for p in positions if p.symbol == "TCS"]
    assert len(tcs) == 0


# ---------------------------------------------------------------------------
# Portfolio tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_paper_positions_after_buy(adapter, sample_order):
    await adapter.login(credentials={})
    await adapter.place_order(sample_order)
    positions = await adapter.get_positions()
    assert len(positions) == 1
    pos = positions[0]
    assert pos.symbol == "RELIANCE"
    assert pos.quantity == 10


@pytest.mark.asyncio
async def test_paper_get_margins_initial(adapter):
    """Before any trades, full capital available, zero used."""
    await adapter.login(credentials={})
    margin = await adapter.get_margins()
    assert margin.total_margin == 1_000_000
    assert margin.used_margin == 0.0
    assert margin.available_cash == 1_000_000


@pytest.mark.asyncio
async def test_paper_margin_deducted(adapter, sample_order):
    """After a BUY, used_margin increases and available_cash decreases."""
    await adapter.login(credentials={})
    await adapter.place_order(sample_order)
    margin = await adapter.get_margins()
    assert margin.used_margin > 0
    assert margin.available_cash < 1_000_000


@pytest.mark.asyncio
async def test_paper_holdings_empty(adapter):
    await adapter.login(credentials={})
    holdings = await adapter.get_holdings()
    assert holdings == []
