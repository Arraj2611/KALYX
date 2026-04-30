"""Tests for PolymarketSource (read-only, mocked HTTP)."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def test_polymarket_name():
    from app.intelligence.sources.polymarket_source import PolymarketSource
    src = PolymarketSource()
    assert src.name == "polymarket"


def test_polymarket_supports():
    from app.intelligence.sources.polymarket_source import PolymarketSource
    src = PolymarketSource()
    assert src.supports("get_polymarket_odds") is True
    assert src.supports("get_ohlcv") is False


@pytest.mark.asyncio
async def test_polymarket_get_odds():
    from app.intelligence.sources.polymarket_source import PolymarketSource
    src = PolymarketSource()
    fake_response = MagicMock()
    fake_response.status_code = 200
    fake_response.json.return_value = [
        {"slug": "fed-rate-cut-jun", "outcomePrices": ["0.82", "0.18"]},
        {"slug": "war-escalation", "outcomePrices": ["0.15", "0.85"]},
    ]
    fake_response.raise_for_status = MagicMock()

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=fake_response):
        result = await src.fetch("get_polymarket_odds", limit=5)
    assert isinstance(result, dict)
    assert "fed-rate-cut-jun" in result
    assert result["fed-rate-cut-jun"] == pytest.approx(0.82)
