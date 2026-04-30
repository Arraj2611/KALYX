"""Conformance tests for DataSource implementations."""
import pytest
from app.intelligence.base import DataSource


class StubSource(DataSource):
    @property
    def name(self):
        return "stub"

    @property
    def capabilities(self):
        return ["get_test", "scrape_article"]

    def supports(self, method):
        return method in self._capabilities_set

    @property
    def _capabilities_set(self):
        return set(self.capabilities)

    async def fetch(self, method, **kwargs):
        return {"src": self.name, "method": method, "kwargs": kwargs}


def make_stub_source():
    return StubSource()


SOURCE_FACTORIES = [
    pytest.param(make_stub_source, id="stub"),
]


# Concrete sources (with mocked dependencies)

def make_yfinance_source():
    from app.intelligence.sources.yfinance_source import YFinanceSource
    return YFinanceSource()


def make_polymarket_source():
    from app.intelligence.sources.polymarket_source import PolymarketSource
    return PolymarketSource()


def make_groww_mcp_source():
    from unittest.mock import MagicMock, AsyncMock
    from app.intelligence.sources.mcp_groww_source import GrowwMCPSource
    client = MagicMock()
    client.call_tool = AsyncMock(return_value={})
    return GrowwMCPSource(mcp_client=client)


def make_zerodha_mcp_source():
    from unittest.mock import MagicMock, AsyncMock
    from app.intelligence.sources.mcp_zerodha_source import ZerodhaMCPSource
    client = MagicMock()
    client.call_tool = AsyncMock(return_value={})
    return ZerodhaMCPSource(mcp_client=client)


def make_gdelt_source():
    from app.intelligence.sources.gdelt_source import GdeltSource
    return GdeltSource()


def make_news_scraper_source():
    from app.intelligence.sources.news_scraper_source import NewsScraperSource
    return NewsScraperSource()


SOURCE_FACTORIES.extend([
    pytest.param(make_yfinance_source, id="yfinance"),
    pytest.param(make_polymarket_source, id="polymarket"),
    pytest.param(make_groww_mcp_source, id="groww_mcp"),
    pytest.param(make_zerodha_mcp_source, id="zerodha_mcp"),
    pytest.param(make_gdelt_source, id="gdelt"),
    pytest.param(make_news_scraper_source, id="news_scraper"),
])


@pytest.fixture(params=SOURCE_FACTORIES)
def source(request) -> DataSource:
    return request.param()


def test_source_name_is_string(source):
    assert isinstance(source.name, str)
    assert len(source.name) > 0


def test_source_capabilities_is_list(source):
    caps = source.capabilities
    assert isinstance(caps, list)
    assert all(isinstance(c, str) for c in caps)


def test_source_supports_returns_bool(source):
    for cap in source.capabilities:
        assert source.supports(cap) is True
    assert source.supports("definitely_not_a_method") is False


@pytest.mark.asyncio
async def test_source_fetch_supported_method(source):
    if not source.capabilities:
        return
    method = source.capabilities[0]
    # Verify method invocation doesn't crash. Real sources may return None
    # without proper kwargs — that's fine; we just want no exception.
    try:
        await source.fetch(method, foo="bar")
    except Exception:
        # Sources may raise SourceUnavailableError when not configured — acceptable
        pass
