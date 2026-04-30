"""DataSource abstract interface and error types for intelligence layer."""
from abc import ABC, abstractmethod
from typing import Any


class RateLimitError(Exception):
    """Source rate-limited. Triggers fallback to next vendor."""
    pass


class SourceUnavailableError(Exception):
    """Source unreachable or returned a fatal error. Triggers fallback."""
    pass


class DataSource(ABC):
    """Abstract data source.

    Each broker MCP, market data SDK, or scraper implements this interface.
    The DataSourceRegistry routes method calls to registered sources with
    primary + fallback chains based on per-category configuration.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Short stable identifier (e.g. 'yfinance', 'polymarket', 'groww_mcp')."""
        ...

    @property
    @abstractmethod
    def capabilities(self) -> list[str]:
        """Methods this source can serve (e.g. ['get_ohlcv', 'get_news'])."""
        ...

    @abstractmethod
    def supports(self, method: str) -> bool:
        """Whether the source can serve the given method."""
        ...

    @abstractmethod
    async def fetch(self, method: str, **kwargs) -> Any:
        """Fetch data for the given method.

        Raises:
            RateLimitError: source rate-limited
            SourceUnavailableError: source unreachable
        """
        ...
