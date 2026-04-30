"""Tests for DataSourceRegistry routing + fallback."""
import pytest
from app.intelligence.base import DataSource, RateLimitError, SourceUnavailableError
from app.intelligence.registry import DataSourceRegistry


class MockSource(DataSource):
    def __init__(self, name, capabilities, fetch_impl=None):
        self._name = name
        self._capabilities = capabilities
        self._fetch_impl = fetch_impl or (lambda method, **kw: {"src": name, "method": method})

    @property
    def name(self):
        return self._name

    @property
    def capabilities(self):
        return self._capabilities

    def supports(self, method):
        return method in self._capabilities

    async def fetch(self, method, **kwargs):
        result = self._fetch_impl(method, **kwargs)
        if isinstance(result, Exception):
            raise result
        return result


@pytest.fixture
def basic_config():
    return {
        "data_vendors": {
            "ohlcv": "yfinance,zerodha_mcp",
            "news": "trafilatura,gdelt",
            "odds": "polymarket",
        }
    }


# --- 1. test_registry_creation ---
def test_registry_creation(basic_config):
    reg = DataSourceRegistry(basic_config)
    assert reg is not None


# --- 2. test_register_and_get_source ---
def test_register_and_get_source(basic_config):
    reg = DataSourceRegistry(basic_config)
    src = MockSource("yfinance", ["get_ohlcv", "get_ltp"])
    reg.register(src)
    assert reg.get_source("yfinance") is src


# --- 3. test_get_unknown_source_raises ---
def test_get_unknown_source_raises(basic_config):
    reg = DataSourceRegistry(basic_config)
    with pytest.raises(KeyError):
        reg.get_source("nonexistent_source")


# --- 4. test_get_category_for_method ---
def test_get_category_for_method(basic_config):
    reg = DataSourceRegistry(basic_config)
    assert reg.get_category_for_method("get_ohlcv") == "ohlcv"
    assert reg.get_category_for_method("get_news") == "news"
    assert reg.get_category_for_method("get_polymarket_odds") == "odds"


# --- 5. test_get_category_for_unknown_method_raises ---
def test_get_category_for_unknown_method_raises(basic_config):
    reg = DataSourceRegistry(basic_config)
    with pytest.raises(ValueError):
        reg.get_category_for_method("get_nonsense")


# --- 6. test_get_vendor_chain ---
def test_get_vendor_chain(basic_config):
    reg = DataSourceRegistry(basic_config)
    chain = reg.get_vendor_chain("get_ohlcv")
    assert chain == ["yfinance", "zerodha_mcp"]


# --- 7. test_fetch_uses_primary ---
@pytest.mark.asyncio
async def test_fetch_uses_primary(basic_config):
    reg = DataSourceRegistry(basic_config)
    calls = []

    def primary_impl(method, **kw):
        calls.append("yfinance")
        return {"src": "yfinance", "method": method}

    reg.register(MockSource("yfinance", ["get_ohlcv"], fetch_impl=primary_impl))
    reg.register(MockSource("zerodha_mcp", ["get_ohlcv"]))

    result = await reg.fetch("get_ohlcv", symbol="RELIANCE")
    assert result["src"] == "yfinance"
    assert calls == ["yfinance"]


# --- 8. test_fetch_falls_back_on_rate_limit ---
@pytest.mark.asyncio
async def test_fetch_falls_back_on_rate_limit(basic_config):
    reg = DataSourceRegistry(basic_config)

    def rate_limited(method, **kw):
        return RateLimitError("rate limited")

    reg.register(MockSource("yfinance", ["get_ohlcv"], fetch_impl=rate_limited))
    reg.register(MockSource("zerodha_mcp", ["get_ohlcv"]))

    result = await reg.fetch("get_ohlcv", symbol="RELIANCE")
    assert result["src"] == "zerodha_mcp"


# --- 9. test_fetch_falls_back_on_source_unavailable ---
@pytest.mark.asyncio
async def test_fetch_falls_back_on_source_unavailable(basic_config):
    reg = DataSourceRegistry(basic_config)

    def unavailable(method, **kw):
        return SourceUnavailableError("down")

    reg.register(MockSource("yfinance", ["get_ohlcv"], fetch_impl=unavailable))
    reg.register(MockSource("zerodha_mcp", ["get_ohlcv"]))

    result = await reg.fetch("get_ohlcv", symbol="RELIANCE")
    assert result["src"] == "zerodha_mcp"


# --- 10. test_fetch_skips_unsupported_source ---
@pytest.mark.asyncio
async def test_fetch_skips_unsupported_source(basic_config):
    reg = DataSourceRegistry(basic_config)
    # yfinance registered but does NOT support get_ohlcv
    reg.register(MockSource("yfinance", ["get_news"]))
    reg.register(MockSource("zerodha_mcp", ["get_ohlcv"]))

    result = await reg.fetch("get_ohlcv")
    assert result["src"] == "zerodha_mcp"


# --- 11. test_fetch_exhausts_chain_raises ---
@pytest.mark.asyncio
async def test_fetch_exhausts_chain_raises(basic_config):
    reg = DataSourceRegistry(basic_config)

    def always_fail(method, **kw):
        return RateLimitError("always rate limited")

    reg.register(MockSource("yfinance", ["get_ohlcv"], fetch_impl=always_fail))
    reg.register(MockSource("zerodha_mcp", ["get_ohlcv"], fetch_impl=always_fail))

    with pytest.raises(RateLimitError):
        await reg.fetch("get_ohlcv")


# --- 12. test_fetch_no_vendors_raises ---
@pytest.mark.asyncio
async def test_fetch_no_vendors_raises(basic_config):
    reg = DataSourceRegistry(basic_config)
    # No sources registered at all

    with pytest.raises(RuntimeError, match="No vendor available"):
        await reg.fetch("get_ohlcv")
