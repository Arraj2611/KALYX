"""GDELT geopolitical event source via gdelt-doc-api."""
import asyncio
import logging
from typing import Any

from app.intelligence.base import DataSource, SourceUnavailableError

logger = logging.getLogger(__name__)


try:
    from gdeltdoc import GdeltDoc, Filters
except ImportError:
    GdeltDoc = None
    Filters = None


class GdeltSource(DataSource):
    """GDELT 2.0 article search."""

    _CAPABILITIES = ["get_gdelt_events", "get_news", "get_global_news"]

    @property
    def name(self) -> str:
        return "gdelt"

    @property
    def capabilities(self) -> list[str]:
        return list(self._CAPABILITIES)

    def supports(self, method: str) -> bool:
        return method in self._CAPABILITIES

    async def fetch(self, method: str, **kwargs) -> Any:
        if GdeltDoc is None or Filters is None:
            raise SourceUnavailableError("gdelt-doc-api not installed")

        keyword = kwargs.get("keyword") or kwargs.get("symbol", "")
        if not keyword:
            return []

        def _sync_fetch():
            f = Filters(keyword=keyword, timespan="1d")
            client = GdeltDoc()
            articles = client.article_search(f)
            if hasattr(articles, "to_dict"):
                return articles.to_dict("records")
            return list(articles) if articles else []

        try:
            return await asyncio.to_thread(_sync_fetch)
        except Exception as exc:
            raise SourceUnavailableError(f"gdelt fetch failed: {exc}")
