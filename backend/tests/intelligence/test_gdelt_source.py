"""Tests for GdeltSource."""
import pytest
from unittest.mock import MagicMock, patch


def test_gdelt_name():
    from app.intelligence.sources.gdelt_source import GdeltSource
    src = GdeltSource()
    assert src.name == "gdelt"


def test_gdelt_supports():
    from app.intelligence.sources.gdelt_source import GdeltSource
    src = GdeltSource()
    assert src.supports("get_gdelt_events") is True
    assert src.supports("get_news") is True


@pytest.mark.asyncio
async def test_gdelt_get_events():
    from app.intelligence.sources.gdelt_source import GdeltSource
    src = GdeltSource()
    fake_filters = MagicMock()
    fake_client = MagicMock()
    fake_client.article_search.return_value = [
        {"title": "Event 1", "url": "http://e1", "domain": "src.com"},
    ]

    with patch("app.intelligence.sources.gdelt_source.Filters", return_value=fake_filters), \
         patch("app.intelligence.sources.gdelt_source.GdeltDoc", return_value=fake_client):
        result = await src.fetch("get_gdelt_events", keyword="oil")
    assert isinstance(result, list)
