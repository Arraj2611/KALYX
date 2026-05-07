"""Scrapling news scraper — primary news source.

Uses Scrapling's Fetcher for HTTP+TLS-impersonation by default. Falls back
to StealthyFetcher when Cloudflare is detected. Lazy import so the module
is importable without scrapling installed.
"""
import asyncio
import logging
from typing import Any

from app.intelligence.base import DataSource, RateLimitError, SourceUnavailableError

logger = logging.getLogger(__name__)


class ScraplingSource(DataSource):
    """Web scraper using Scrapling. Handles Cloudflare, JS-heavy news sites."""

    @property
    def name(self) -> str:
        return "scrapling"

    @property
    def capabilities(self) -> list[str]:
        return ["scrape_article"]

    def supports(self, method: str) -> bool:
        return method == "scrape_article"

    async def fetch(self, method: str, **kwargs) -> Any:
        url = kwargs.get("url", "")
        if not url:
            return None

        # Lazy import — scrapling is optional
        try:
            from scrapling.fetchers import Fetcher
        except ImportError as exc:
            raise SourceUnavailableError(f"scrapling not installed: {exc}")

        def _sync_fetch():
            try:
                page = Fetcher.get(url, stealthy_headers=True, follow_redirects=True)
            except Exception as exc:
                # Try stealthy fetcher on first failure (Cloudflare etc.)
                try:
                    from scrapling.fetchers import StealthyFetcher
                    page = StealthyFetcher.fetch(url)
                except Exception as inner_exc:
                    raise SourceUnavailableError(
                        f"scrapling fetch failed: {exc} / {inner_exc}"
                    )

            # Extract text — Scrapling exposes get_all_text or .text on body
            text = ""
            try:
                if hasattr(page, "get_all_text"):
                    text = page.get_all_text()
                elif hasattr(page, "text"):
                    text = page.text
                else:
                    text = str(page)
            except Exception:
                text = ""

            if not text:
                return None
            return {"url": url, "text": text}

        try:
            return await asyncio.to_thread(_sync_fetch)
        except SourceUnavailableError:
            raise
        except Exception as exc:
            raise SourceUnavailableError(f"scrapling fetch failed: {exc}")
