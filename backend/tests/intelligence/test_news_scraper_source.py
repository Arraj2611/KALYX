"""Tests for NewsScraperSource (trafilatura)."""
import pytest
from unittest.mock import patch


def test_news_scraper_name():
    from app.intelligence.sources.news_scraper_source import NewsScraperSource
    src = NewsScraperSource()
    assert src.name == "trafilatura"


def test_news_scraper_supports():
    from app.intelligence.sources.news_scraper_source import NewsScraperSource
    src = NewsScraperSource()
    assert src.supports("scrape_article") is True


@pytest.mark.asyncio
async def test_news_scraper_extracts_article():
    import sys
    from unittest.mock import MagicMock
    from app.intelligence.sources.news_scraper_source import NewsScraperSource
    src = NewsScraperSource()
    fake_trafilatura = MagicMock()
    fake_trafilatura.fetch_url.return_value = "<html><body>test</body></html>"
    fake_trafilatura.extract.return_value = "Extracted text body."
    with patch.dict(sys.modules, {"trafilatura": fake_trafilatura}):
        result = await src.fetch("scrape_article", url="http://example.com")
    assert result is not None
    assert result["text"] == "Extracted text body."


@pytest.mark.asyncio
async def test_news_scraper_returns_none_on_failure():
    import sys
    from unittest.mock import MagicMock
    from app.intelligence.sources.news_scraper_source import NewsScraperSource
    src = NewsScraperSource()
    fake_trafilatura = MagicMock()
    fake_trafilatura.fetch_url.return_value = None
    with patch.dict(sys.modules, {"trafilatura": fake_trafilatura}):
        result = await src.fetch("scrape_article", url="http://broken.com")
    assert result is None or result.get("text") in (None, "")
