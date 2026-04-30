"""Zerodha MCP data source."""
import logging
from typing import Any

from app.intelligence.base import DataSource, SourceUnavailableError

logger = logging.getLogger(__name__)


_METHOD_TO_MCP_TOOL = {
    "get_ltp": "get_ltp",
    "get_quotes": "get_quote",
    "get_ohlcv": "get_ohlc",
}


class ZerodhaMCPSource(DataSource):
    """Wraps Zerodha (kite-mcp) server tools."""

    def __init__(self, mcp_client: Any):
        self._client = mcp_client

    @property
    def name(self) -> str:
        return "zerodha_mcp"

    @property
    def capabilities(self) -> list[str]:
        return list(_METHOD_TO_MCP_TOOL.keys())

    def supports(self, method: str) -> bool:
        return method in _METHOD_TO_MCP_TOOL

    async def fetch(self, method: str, **kwargs) -> Any:
        tool = _METHOD_TO_MCP_TOOL.get(method)
        if tool is None:
            raise SourceUnavailableError(f"zerodha_mcp does not support {method}")
        try:
            return await self._client.call_tool(tool, **kwargs)
        except Exception as exc:
            raise SourceUnavailableError(f"zerodha_mcp call failed: {exc}")
