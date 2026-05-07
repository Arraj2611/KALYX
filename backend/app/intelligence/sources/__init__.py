"""Concrete data sources for intelligence layer."""
from app.intelligence.sources.yfinance_source import YFinanceSource
from app.intelligence.sources.polymarket_source import PolymarketSource
from app.intelligence.sources.mcp_groww_source import GrowwMCPSource
from app.intelligence.sources.mcp_zerodha_source import ZerodhaMCPSource
from app.intelligence.sources.gdelt_source import GdeltSource
from app.intelligence.sources.news_scraper_source import NewsScraperSource
from app.intelligence.sources.scrapling_source import ScraplingSource

__all__ = [
    "YFinanceSource",
    "PolymarketSource",
    "GrowwMCPSource",
    "ZerodhaMCPSource",
    "GdeltSource",
    "NewsScraperSource",
    "ScraplingSource",
]
