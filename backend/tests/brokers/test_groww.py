"""Unit tests for GrowwAdapter.

All growwapi SDK calls are mocked — no real network or credentials needed.
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock

from app.brokers.base import (
    BrokerAdapter,
    MarginInfo,
    OrderResult,
    Position,
    UnifiedOrder,
)
from app.brokers.groww.adapter import GrowwAdapter


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_groww():
    g = MagicMock()
    g.place_order.return_value = {"groww_order_id": "GRW123", "order_status": "OPEN"}
    g.get_positions_for_user.return_value = [
        {
            "trading_symbol": "RELIANCE",
            "segment": "CASH",
            "exchange": "NSE",
            "quantity": 10,
            "net_price": 2500.0,
            "credit_price": 2500.0,
            "product": "CNC",
            "realised_pnl": 0,
        }
    ]
    g.get_available_margin_details.return_value = {
        "clear_cash": 400000.0,
        "net_margin_used": 100000.0,
    }
    g.cancel_order.return_value = {
        "groww_order_id": "GRW123",
        "order_status": "CANCELLED",
    }
    g.get_order_list.return_value = {"order_list": []}
    g.get_holdings_for_user.return_value = []
    g.get_ltp.return_value = {"NSE_RELIANCE": 2550.0}
    g.get_all_instruments.return_value = MagicMock()
    return g


@pytest.fixture
def groww_adapter(mock_groww):
    """Return a GrowwAdapter pre-seeded with a mock client (no real login)."""
    adapter = GrowwAdapter()
    adapter._client = mock_groww
    adapter._logged_in = True
    return adapter


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_groww_is_broker_adapter(groww_adapter):
    assert isinstance(groww_adapter, BrokerAdapter)


def test_groww_name(groww_adapter):
    assert groww_adapter.name == "groww"


@pytest.mark.asyncio
async def test_groww_place_order(groww_adapter, mock_groww):
    order = UnifiedOrder(
        symbol="RELIANCE",
        exchange="NSE",
        segment="CASH",
        transaction_type="BUY",
        quantity=5,
        order_type="LIMIT",
        product="CNC",
        price=2500.0,
    )
    result = await groww_adapter.place_order(order)
    assert isinstance(result, OrderResult)
    assert result.broker_order_id == "GRW123"
    assert result.broker_name == "groww"
    mock_groww.place_order.assert_called_once()


@pytest.mark.asyncio
async def test_groww_get_positions(groww_adapter):
    positions = await groww_adapter.get_positions()
    assert len(positions) == 1
    pos = positions[0]
    assert isinstance(pos, Position)
    assert pos.symbol == "RELIANCE"
    assert pos.broker_name == "groww"


@pytest.mark.asyncio
async def test_groww_get_margins(groww_adapter):
    margin = await groww_adapter.get_margins()
    assert isinstance(margin, MarginInfo)
    assert margin.available_cash == 400000.0
    assert margin.broker_name == "groww"


@pytest.mark.asyncio
async def test_groww_cancel_order(groww_adapter, mock_groww):
    result = await groww_adapter.cancel_order("GRW123", "CASH")
    assert result == "GRW123"
    mock_groww.cancel_order.assert_called_once()
