"""Tests for YFinanceSource (mocked yfinance.Ticker)."""
import pytest
from unittest.mock import MagicMock, patch


@pytest.fixture
def mock_ticker():
    t = MagicMock()
    hist = MagicMock()
    hist.to_dict.return_value = {"Close": {0: 100.0}, "Volume": {0: 1000}}
    hist.empty = False
    t.history.return_value = hist
    t.news = [{"title": "Big news", "link": "https://example.com/news"}]
    t.info = {"sector": "Tech"}
    return t


def test_yfinance_name():
    from app.intelligence.sources.yfinance_source import YFinanceSource
    src = YFinanceSource()
    assert src.name == "yfinance"


def test_yfinance_supports():
    from app.intelligence.sources.yfinance_source import YFinanceSource
    src = YFinanceSource()
    assert src.supports("get_ohlcv") is True
    assert src.supports("nonexistent") is False


@pytest.mark.asyncio
async def test_yfinance_get_ohlcv(mock_ticker):
    import sys
    from unittest.mock import MagicMock
    from app.intelligence.sources.yfinance_source import YFinanceSource
    src = YFinanceSource()
    fake_yfinance = MagicMock()
    fake_yfinance.Ticker.return_value = mock_ticker
    with patch.dict(sys.modules, {"yfinance": fake_yfinance}):
        result = await src.fetch("get_ohlcv", symbol="AAPL", period="5d")
    assert result is not None
    assert "Close" in result


@pytest.mark.asyncio
async def test_yfinance_get_news(mock_ticker):
    import sys
    from unittest.mock import MagicMock
    from app.intelligence.sources.yfinance_source import YFinanceSource
    src = YFinanceSource()
    fake_yfinance = MagicMock()
    fake_yfinance.Ticker.return_value = mock_ticker
    with patch.dict(sys.modules, {"yfinance": fake_yfinance}):
        result = await src.fetch("get_news", symbol="AAPL")
    assert isinstance(result, list)
    assert len(result) >= 1
