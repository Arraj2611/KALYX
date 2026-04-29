"""
Unit tests for ZerodhaAdapter.

All tests mock KiteConnect so no real Zerodha credentials are required.
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch

from app.brokers.base import (
    BrokerAdapter,
    MarginInfo,
    OrderResult,
    Position,
    UnifiedOrder,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_kite():
    kite = MagicMock()
    kite.generate_session.return_value = {
        "access_token": "tok",
        "public_token": "pub",
        "user_id": "AB1234",
    }
    kite.profile.return_value = {"user_id": "AB1234"}
    kite.place_order.return_value = {"order_id": "ZRD123456"}
    kite.modify_order.return_value = {"order_id": "ZRD123456"}
    kite.cancel_order.return_value = {"order_id": "ZRD123456"}
    kite.positions.return_value = {
        "net": [
            {
                "tradingsymbol": "NIFTY25APR24500CE",
                "exchange": "NFO",
                "quantity": 50,
                "average_price": 150.0,
                "last_price": 160.0,
                "pnl": 500.0,
                "product": "MIS",
            }
        ]
    }
    kite.margins.return_value = {
        "equity": {
            "available": {"cash": 500000.0},
            "utilised": {"debits": 200000.0},
        }
    }
    kite.instruments.return_value = [
        {
            "tradingsymbol": "NIFTY25APR24500CE",
            "instrument_token": 12345,
            "exchange": "NFO",
            "segment": "NFO-OPT",
            "instrument_type": "CE",
            "lot_size": 50,
            "tick_size": 0.05,
            "expiry": "2025-04-24",
            "strike": 24500.0,
        }
    ]
    kite.orders.return_value = []
    kite.holdings.return_value = []
    kite.ltp.return_value = {}
    return kite


@pytest.fixture
def zerodha_adapter(mock_kite):
    """ZerodhaAdapter with KiteConnect patched and already logged-in."""
    with patch("app.brokers.zerodha.adapter.KiteConnect", return_value=mock_kite):
        from app.brokers.zerodha.adapter import ZerodhaAdapter

        adapter = ZerodhaAdapter(api_key="test_key", api_secret="test_secret")
        # Inject mock directly so tests don't need to go through login
        adapter._kite = mock_kite
        adapter._logged_in = True
        yield adapter


# ---------------------------------------------------------------------------
# Identity / capability
# ---------------------------------------------------------------------------


def test_zerodha_is_broker_adapter(zerodha_adapter):
    assert isinstance(zerodha_adapter, BrokerAdapter)


def test_zerodha_name(zerodha_adapter):
    assert zerodha_adapter.name == "zerodha"


def test_zerodha_segments(zerodha_adapter):
    segs = zerodha_adapter.supported_segments
    assert "CASH" in segs
    assert "FNO" in segs


# ---------------------------------------------------------------------------
# Order management
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_zerodha_place_order(zerodha_adapter, mock_kite):
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
    result = await zerodha_adapter.place_order(order)

    assert isinstance(result, OrderResult)
    assert result.broker_order_id == "ZRD123456"
    assert result.broker_name == "zerodha"
    mock_kite.place_order.assert_called_once()


@pytest.mark.asyncio
async def test_zerodha_cancel_order(zerodha_adapter, mock_kite):
    order_id = await zerodha_adapter.cancel_order("ZRD123456", "CASH")
    assert order_id == "ZRD123456"
    mock_kite.cancel_order.assert_called_once_with(
        variety="regular", order_id="ZRD123456"
    )


# ---------------------------------------------------------------------------
# Portfolio
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_zerodha_get_positions(zerodha_adapter):
    positions = await zerodha_adapter.get_positions()

    assert len(positions) == 1
    pos = positions[0]
    assert isinstance(pos, Position)
    assert pos.symbol == "NIFTY25APR24500CE"
    assert pos.broker_name == "zerodha"
    assert pos.quantity == 50
    assert pos.segment == "FNO"  # NFO exchange → FNO segment


@pytest.mark.asyncio
async def test_zerodha_get_margins(zerodha_adapter):
    margin = await zerodha_adapter.get_margins()

    assert isinstance(margin, MarginInfo)
    assert margin.available_cash == 500000.0
    assert margin.broker_name == "zerodha"
