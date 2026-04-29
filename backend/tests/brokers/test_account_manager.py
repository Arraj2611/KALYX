"""Tests for AccountManager — multi-account broker registry."""

import pytest

from app.brokers.account_manager import AccountManager
from app.brokers.base import UnifiedOrder
from app.brokers.paper import PaperAdapter


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def adapter_a():
    """PaperAdapter with 500 000 capital, zero slippage."""
    return PaperAdapter(config={"initial_capital": 500_000, "slippage_pct": 0})


@pytest.fixture
def adapter_b():
    """PaperAdapter with 300 000 capital, zero slippage."""
    return PaperAdapter(config={"initial_capital": 300_000, "slippage_pct": 0})


@pytest.fixture
def manager(adapter_a, adapter_b):
    """AccountManager with two paper adapters pre-registered."""
    mgr = AccountManager()
    mgr.register("paper_a", adapter_a, {"broker": "paper"})
    mgr.register("paper_b", adapter_b, {"broker": "paper"})
    return mgr


@pytest.fixture
def buy_order():
    """Simple BUY order used across multiple tests."""
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
# Synchronous registry tests
# ---------------------------------------------------------------------------


def test_register_and_get(adapter_a):
    mgr = AccountManager()
    mgr.register("acct1", adapter_a, {})
    assert mgr.get_adapter("acct1") is adapter_a


def test_get_nonexistent_raises():
    mgr = AccountManager()
    with pytest.raises(KeyError):
        mgr.get_adapter("does_not_exist")


def test_get_all_adapters(manager, adapter_a, adapter_b):
    all_adapters = manager.get_all_adapters()
    assert "paper_a" in all_adapters
    assert "paper_b" in all_adapters
    assert all_adapters["paper_a"] is adapter_a
    assert all_adapters["paper_b"] is adapter_b


def test_get_adapters_by_broker(manager, adapter_a, adapter_b):
    results = manager.get_adapters_by_broker("paper")
    assert len(results) == 2
    assert adapter_a in results
    assert adapter_b in results


def test_get_adapters_by_broker_empty(manager):
    results = manager.get_adapters_by_broker("zerodha")
    assert results == []


def test_duplicate_registration_raises(adapter_a, adapter_b):
    mgr = AccountManager()
    mgr.register("acct1", adapter_a, {})
    with pytest.raises(ValueError):
        mgr.register("acct1", adapter_b, {})


# ---------------------------------------------------------------------------
# Async cross-account tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_all_positions(adapter_a, adapter_b, buy_order):
    """After placing one order on adapter_a, positions dict has one entry for paper_a."""
    await adapter_a.login(credentials={})
    await adapter_b.login(credentials={})
    await adapter_a.place_order(buy_order)

    mgr = AccountManager()
    mgr.register("paper_a", adapter_a, {})
    mgr.register("paper_b", adapter_b, {})

    positions = await mgr.get_all_positions()

    assert "paper_a" in positions
    assert "paper_b" in positions
    assert len(positions["paper_a"]) == 1
    assert positions["paper_a"][0].symbol == "RELIANCE"
    assert len(positions["paper_b"]) == 0


@pytest.mark.asyncio
async def test_get_all_margins(adapter_a, adapter_b):
    """Each account's MarginInfo reflects its configured capital."""
    await adapter_a.login(credentials={})
    await adapter_b.login(credentials={})

    mgr = AccountManager()
    mgr.register("paper_a", adapter_a, {})
    mgr.register("paper_b", adapter_b, {})

    margins = await mgr.get_all_margins()

    assert "paper_a" in margins
    assert "paper_b" in margins
    assert margins["paper_a"].total_margin == 500_000
    assert margins["paper_b"].total_margin == 300_000


@pytest.mark.asyncio
async def test_get_total_exposure(adapter_a, adapter_b):
    """With no open orders, total exposure across all accounts is 0.0."""
    await adapter_a.login(credentials={})
    await adapter_b.login(credentials={})

    mgr = AccountManager()
    mgr.register("paper_a", adapter_a, {})
    mgr.register("paper_b", adapter_b, {})

    exposure = await mgr.get_total_exposure()
    assert exposure == 0.0
