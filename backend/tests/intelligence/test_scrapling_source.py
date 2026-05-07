"""Tests for ScraplingSource (mocked Scrapling Fetcher)."""
import pytest
import sys
from unittest.mock import MagicMock, patch


def test_scrapling_name():
    from app.intelligence.sources.scrapling_source import ScraplingSource
    src = ScraplingSource()
    assert src.name == "scrapling"


def test_scrapling_supports():
    from app.intelligence.sources.scrapling_source import ScraplingSource
    src = ScraplingSource()
    assert src.supports("scrape_article") is True
    assert src.supports("get_ohlcv") is False


@pytest.mark.asyncio
async def test_scrapling_extracts_article():
    """Mock Scrapling to return an HTML page; verify text extraction."""
    fake_page = MagicMock()
    fake_page.css = MagicMock(return_value=MagicMock(text="Article body"))
    fake_page.html_content = "<html><body>Article body</body></html>"
    fake_page.find_by_text = MagicMock(return_value=None)
    # Mock get_all_text or extract methods used by impl
    fake_page.get_all_text = MagicMock(return_value="Article body content here")

    fake_fetcher_module = MagicMock()
    fake_fetcher = MagicMock()
    fake_fetcher.get = MagicMock(return_value=fake_page)
    fake_fetcher_module.Fetcher = fake_fetcher

    fake_scrapling = MagicMock()
    fake_scrapling.fetchers = fake_fetcher_module

    with patch.dict(sys.modules, {"scrapling": fake_scrapling, "scrapling.fetchers": fake_fetcher_module}):
        from app.intelligence.sources.scrapling_source import ScraplingSource
        src = ScraplingSource()
        result = await src.fetch("scrape_article", url="http://example.com")

    assert result is not None
    assert "url" in result
    assert "text" in result


@pytest.mark.asyncio
async def test_scrapling_returns_none_on_no_url():
    from app.intelligence.sources.scrapling_source import ScraplingSource
    src = ScraplingSource()
    result = await src.fetch("scrape_article")
    assert result is None
