"""yfinance data source — global market OHLCV/news/fundamentals."""
import asyncio
import logging
from typing import Any

from app.intelligence.base import DataSource, SourceUnavailableError

logger = logging.getLogger(__name__)


class YFinanceSource(DataSource):
    """yfinance wrapper. yfinance is sync — wrapped in asyncio.to_thread."""

    _CAPABILITIES = ["get_ohlcv", "get_news", "get_fundamentals", "get_balance_sheet", "get_cashflow"]

    @property
    def name(self) -> str:
        return "yfinance"

    @property
    def capabilities(self) -> list[str]:
        return list(self._CAPABILITIES)

    def supports(self, method: str) -> bool:
        return method in self._CAPABILITIES

    async def fetch(self, method: str, **kwargs) -> Any:
        try:
            import yfinance
        except ImportError as exc:
            raise SourceUnavailableError(f"yfinance not installed: {exc}")

        symbol = kwargs.get("symbol", "")
        if not symbol:
            return None

        def _sync_fetch():
            ticker = yfinance.Ticker(symbol)
            if method == "get_ohlcv":
                period = kwargs.get("period", "5d")
                interval = kwargs.get("interval", "1d")
                hist = ticker.history(period=period, interval=interval)
                if hist.empty:
                    return {}
                return hist.to_dict()
            if method == "get_news":
                return list(ticker.news) if ticker.news else []
            if method == "get_fundamentals":
                return dict(ticker.info)
            if method == "get_balance_sheet":
                bs = ticker.balance_sheet
                return bs.to_dict() if bs is not None and not bs.empty else {}
            if method == "get_cashflow":
                cf = ticker.cashflow
                return cf.to_dict() if cf is not None and not cf.empty else {}
            return None

        try:
            return await asyncio.to_thread(_sync_fetch)
        except Exception as exc:
            raise SourceUnavailableError(f"yfinance fetch failed: {exc}")
