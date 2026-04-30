"""Tests for DataSource ABC and error types."""
import pytest
from app.intelligence.base import DataSource, RateLimitError, SourceUnavailableError


def test_data_source_is_abstract():
    """Instantiating DataSource directly must raise TypeError."""
    with pytest.raises(TypeError):
        DataSource()


def test_rate_limit_error():
    """RateLimitError message is preserved and accessible via str()."""
    err = RateLimitError("yfinance rate limited")
    assert "yfinance" in str(err)


def test_source_unavailable_error():
    """SourceUnavailableError message is preserved and accessible via str()."""
    err = SourceUnavailableError("polymarket unavailable")
    assert "polymarket" in str(err)


def test_data_source_concrete_subclass():
    """A concrete subclass with all abstract methods implemented can be instantiated."""

    class TestSource(DataSource):
        @property
        def name(self) -> str:
            return "test_source"

        @property
        def capabilities(self) -> list[str]:
            return ["get_ohlcv", "get_news"]

        def supports(self, method: str) -> bool:
            return method in self.capabilities

        async def fetch(self, method: str, **kwargs):
            return {"method": method, "data": []}

    source = TestSource()
    assert source.name == "test_source"
    assert source.capabilities == ["get_ohlcv", "get_news"]
    assert source.supports("get_ohlcv") is True
    assert source.supports("unknown_method") is False


@pytest.mark.asyncio
async def test_concrete_subclass_fetch():
    """fetch() on a concrete subclass returns the expected dict."""

    class TestSource(DataSource):
        @property
        def name(self) -> str:
            return "test_source"

        @property
        def capabilities(self) -> list[str]:
            return ["get_ohlcv"]

        def supports(self, method: str) -> bool:
            return method in self.capabilities

        async def fetch(self, method: str, **kwargs):
            return {"method": method, "symbol": kwargs.get("symbol"), "data": [1, 2, 3]}

    source = TestSource()
    result = await source.fetch("get_ohlcv", symbol="AAPL")
    assert result["method"] == "get_ohlcv"
    assert result["symbol"] == "AAPL"
    assert result["data"] == [1, 2, 3]
