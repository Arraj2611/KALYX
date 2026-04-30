"""DataSourceRegistry — routes method calls across registered sources with fallback."""
import logging
from typing import Any

from app.intelligence.base import DataSource, RateLimitError, SourceUnavailableError

logger = logging.getLogger(__name__)


TOOLS_CATEGORIES: dict[str, dict] = {
    "ohlcv":        {"tools": ["get_ohlcv", "get_ltp"]},
    "quotes":       {"tools": ["get_quotes", "get_market_depth"]},
    "news":         {"tools": ["get_news", "get_global_news", "scrape_article"]},
    "odds":         {"tools": ["get_polymarket_odds", "get_event_probability"]},
    "fundamentals": {"tools": ["get_fundamentals", "get_balance_sheet", "get_cashflow"]},
    "geopolitical": {"tools": ["get_gdelt_events"]},
    "screener":     {"tools": ["screen_technical", "screen_fundamental"]},
    "options":      {"tools": ["get_option_chain", "get_greeks", "get_oi"]},
}


class DataSourceRegistry:
    """Registry of data sources with vendor routing + rate-limit fallback chain."""

    def __init__(self, config: dict):
        self._sources: dict[str, DataSource] = {}
        self._vendor_config: dict[str, list[str]] = {}
        self._load_config(config)

    def _load_config(self, config: dict) -> None:
        vendors = config.get("data_vendors", {})
        for category, chain_str in vendors.items():
            chain = [v.strip() for v in str(chain_str).split(",") if v.strip()]
            self._vendor_config[category] = chain

    def register(self, source: DataSource) -> None:
        self._sources[source.name] = source
        logger.info(f"Registered data source: {source.name} (capabilities={source.capabilities})")

    def get_source(self, name: str) -> DataSource:
        if name not in self._sources:
            raise KeyError(f"Source '{name}' not registered")
        return self._sources[name]

    def get_category_for_method(self, method: str) -> str:
        for cat, info in TOOLS_CATEGORIES.items():
            if method in info["tools"]:
                return cat
        raise ValueError(f"Unknown method: {method}")

    def get_vendor_chain(self, method: str) -> list[str]:
        category = self.get_category_for_method(method)
        return self._vendor_config.get(category, [])

    async def fetch(self, method: str, **kwargs) -> Any:
        chain = self.get_vendor_chain(method)
        last_error: Exception | None = None

        for vendor_name in chain:
            if vendor_name not in self._sources:
                continue
            source = self._sources[vendor_name]
            if not source.supports(method):
                continue
            try:
                return await source.fetch(method, **kwargs)
            except (RateLimitError, SourceUnavailableError) as exc:
                logger.warning(f"Source {vendor_name} failed for {method}: {exc}")
                last_error = exc
                continue

        if last_error:
            raise last_error
        raise RuntimeError(f"No vendor available for '{method}'")
