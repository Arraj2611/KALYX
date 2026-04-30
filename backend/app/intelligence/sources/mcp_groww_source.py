"""Groww MCP data source — wraps existing Groww MCP server tools."""
import logging
from typing import Any

from app.intelligence.base import DataSource, SourceUnavailableError

logger = logging.getLogger(__name__)


_METHOD_TO_MCP_TOOL = {
    "get_ltp": "get_ltp",
    "get_quotes": "get_quotes_and_depth",
    "get_market_depth": "get_quotes_and_depth",
    "get_oi": "get_open_interest_analysis",
    "get_option_chain": "get_atm_straddle_chart",
    "get_greeks": "get_greeks_for_fno_symbol",
    "screen_technical": "fetch_technical_screener",
    "screen_fundamental": "fetch_fundamentals_screener",
}


class GrowwMCPSource(DataSource):
    """Wraps Groww MCP server tools."""

    def __init__(self, mcp_client: Any):
        self._client = mcp_client

    @property
    def name(self) -> str:
        return "groww_mcp"

    @property
    def capabilities(self) -> list[str]:
        return list(_METHOD_TO_MCP_TOOL.keys())

    def supports(self, method: str) -> bool:
        return method in _METHOD_TO_MCP_TOOL

    async def fetch(self, method: str, **kwargs) -> Any:
        tool = _METHOD_TO_MCP_TOOL.get(method)
        if tool is None:
            raise SourceUnavailableError(f"groww_mcp does not support {method}")
        try:
            return await self._client.call_tool(tool, **kwargs)
        except Exception as exc:
            raise SourceUnavailableError(f"groww_mcp call failed: {exc}")
