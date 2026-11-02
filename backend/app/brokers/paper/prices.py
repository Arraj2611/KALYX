"""Price source for paper accounts, backed by Yahoo Finance.

Plug it into ``PaperAdapter(price_source=...)``. Yahoo's quotes for Indian symbols can run
minutes behind the exchange, which is acceptable for paper trading but not for live orders.
"""

from __future__ import annotations

import asyncio
import logging
import math

logger = logging.getLogger(__name__)


class YahooPriceSource:
    """Last traded price per KALYX symbol, via a symbol -> Yahoo ticker map.

    A symbol that is unmapped, that Yahoo cannot price, or that prices at zero or NaN is left
    out of the result, which is how the pod learns there is no price.
    """

    def __init__(self, symbol_map: dict[str, str]) -> None:
        self._map = dict(symbol_map)

    async def __call__(self, symbols: list[str]) -> dict[str, float]:
        return await asyncio.to_thread(self._fetch, list(symbols))

    def _fetch(self, symbols: list[str]) -> dict[str, float]:
        try:
            import yfinance
        except ImportError:
            logger.warning("yfinance is not installed: paper accounts have no prices")
            return {}
        prices: dict[str, float] = {}
        for symbol in symbols:
            ticker = self._map.get(symbol)
            if not ticker:
                continue
            try:
                price = float(yfinance.Ticker(ticker).fast_info["last_price"])
            except Exception as exc:  # noqa: BLE001
                logger.warning("No Yahoo price for %s (%s): %s", symbol, ticker, exc)
                continue
            if math.isfinite(price) and price > 0:
                prices[symbol] = price
        return prices
