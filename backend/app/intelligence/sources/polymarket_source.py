"""Polymarket read-only data source — odds, event probabilities."""
import logging
from typing import Any

import httpx

from app.intelligence.base import DataSource, RateLimitError, SourceUnavailableError

logger = logging.getLogger(__name__)


class PolymarketSource(DataSource):
    """Read-only Polymarket CLOB API wrapper."""

    _CAPABILITIES = ["get_polymarket_odds", "get_event_probability"]

    def __init__(self, host: str = "https://clob.polymarket.com", gamma_host: str = "https://gamma-api.polymarket.com"):
        self._host = host
        self._gamma_host = gamma_host

    @property
    def name(self) -> str:
        return "polymarket"

    @property
    def capabilities(self) -> list[str]:
        return list(self._CAPABILITIES)

    def supports(self, method: str) -> bool:
        return method in self._CAPABILITIES

    async def fetch(self, method: str, **kwargs) -> Any:
        try:
            if method == "get_polymarket_odds":
                limit = kwargs.get("limit", 20)
                return await self._fetch_odds(limit)
            if method == "get_event_probability":
                slug = kwargs.get("slug", "")
                return await self._fetch_event_probability(slug)
            return None
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 429:
                raise RateLimitError(f"polymarket rate limited: {exc}")
            raise SourceUnavailableError(f"polymarket http error: {exc}")
        except httpx.HTTPError as exc:
            raise SourceUnavailableError(f"polymarket http error: {exc}")

    async def _fetch_odds(self, limit: int) -> dict[str, float]:
        url = f"{self._gamma_host}/markets"
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url, params={"limit": limit, "active": "true"})
            resp.raise_for_status()
            data = resp.json()
        odds: dict[str, float] = {}
        for market in data:
            slug = market.get("slug")
            prices = market.get("outcomePrices") or []
            if slug and prices:
                try:
                    odds[slug] = float(prices[0])
                except (ValueError, TypeError):
                    continue
        return odds

    async def _fetch_event_probability(self, slug: str) -> float | None:
        if not slug:
            return None
        url = f"{self._gamma_host}/markets"
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url, params={"slug": slug})
            resp.raise_for_status()
            data = resp.json()
        if not data:
            return None
        prices = data[0].get("outcomePrices") or []
        if not prices:
            return None
        try:
            return float(prices[0])
        except (ValueError, TypeError):
            return None
