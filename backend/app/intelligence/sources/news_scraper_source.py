"""trafilatura news article extraction."""
import asyncio
import logging
from typing import Any

from app.intelligence.base import DataSource, SourceUnavailableError

logger = logging.getLogger(__name__)


class NewsScraperSource(DataSource):
    """Extracts clean text from news article URLs via trafilatura."""

    @property
    def name(self) -> str:
        return "trafilatura"

    @property
    def capabilities(self) -> list[str]:
        return ["scrape_article"]

    def supports(self, method: str) -> bool:
        return method == "scrape_article"

    async def fetch(self, method: str, **kwargs) -> Any:
        try:
            import trafilatura
        except ImportError as exc:
            raise SourceUnavailableError(f"trafilatura not installed: {exc}")

        url = kwargs.get("url", "")
        if not url:
            return None

        def _sync_fetch():
            downloaded = trafilatura.fetch_url(url)
            if not downloaded:
                return None
            text = trafilatura.extract(downloaded)
            if not text:
                return None
            return {"url": url, "text": text}

        try:
            return await asyncio.to_thread(_sync_fetch)
        except Exception as exc:
            raise SourceUnavailableError(f"trafilatura fetch failed: {exc}")
