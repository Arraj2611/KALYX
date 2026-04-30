"""Tests for GrowwMCPSource and ZerodhaMCPSource."""
import pytest
from unittest.mock import AsyncMock, MagicMock


@pytest.fixture
def mock_mcp_client():
    client = MagicMock()
    client.call_tool = AsyncMock(return_value={"data": "mcp_result"})
    return client


def test_groww_mcp_name(mock_mcp_client):
    from app.intelligence.sources.mcp_groww_source import GrowwMCPSource
    src = GrowwMCPSource(mcp_client=mock_mcp_client)
    assert src.name == "groww_mcp"


def test_groww_mcp_supports(mock_mcp_client):
    from app.intelligence.sources.mcp_groww_source import GrowwMCPSource
    src = GrowwMCPSource(mcp_client=mock_mcp_client)
    assert src.supports("get_ltp") is True
    assert src.supports("get_oi") is True


@pytest.mark.asyncio
async def test_groww_mcp_fetch(mock_mcp_client):
    from app.intelligence.sources.mcp_groww_source import GrowwMCPSource
    src = GrowwMCPSource(mcp_client=mock_mcp_client)
    result = await src.fetch("get_ltp", symbol="NIFTY")
    assert result == {"data": "mcp_result"}
    mock_mcp_client.call_tool.assert_called_once()


def test_zerodha_mcp_name(mock_mcp_client):
    from app.intelligence.sources.mcp_zerodha_source import ZerodhaMCPSource
    src = ZerodhaMCPSource(mcp_client=mock_mcp_client)
    assert src.name == "zerodha_mcp"


@pytest.mark.asyncio
async def test_zerodha_mcp_fetch(mock_mcp_client):
    from app.intelligence.sources.mcp_zerodha_source import ZerodhaMCPSource
    src = ZerodhaMCPSource(mcp_client=mock_mcp_client)
    result = await src.fetch("get_ltp", symbol="RELIANCE")
    assert result is not None
