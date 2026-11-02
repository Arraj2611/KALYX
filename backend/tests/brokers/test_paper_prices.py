"""YahooPriceSource: last prices for paper accounts, with yfinance faked."""

import sys
import types

import pytest

from app.brokers.paper.prices import YahooPriceSource


def fake_yfinance(monkeypatch, quotes):
    """quotes: ticker -> last price, or an Exception to raise."""
    module = types.ModuleType("yfinance")

    class Ticker:
        def __init__(self, name):
            self.name = name

        @property
        def fast_info(self):
            value = quotes[self.name]
            if isinstance(value, Exception):
                raise value
            return {"last_price": value}

    module.Ticker = Ticker
    monkeypatch.setitem(sys.modules, "yfinance", module)


@pytest.mark.asyncio
async def test_symbols_are_mapped_to_yahoo_tickers(monkeypatch):
    fake_yfinance(monkeypatch, {"^NSEI": 24500.5, "RELIANCE.NS": 2900.0})
    source = YahooPriceSource({"NIFTY": "^NSEI", "RELIANCE": "RELIANCE.NS"})
    assert await source(["NIFTY", "RELIANCE"]) == {"NIFTY": 24500.5, "RELIANCE": 2900.0}


@pytest.mark.asyncio
async def test_unmapped_failing_and_unusable_prices_are_left_out(monkeypatch):
    fake_yfinance(monkeypatch, {"A.NS": RuntimeError("rate limited"), "B.NS": 0.0, "C.NS": float("nan"), "D.NS": 5.0})
    source = YahooPriceSource({"A": "A.NS", "B": "B.NS", "C": "C.NS", "D": "D.NS"})
    assert await source(["A", "B", "C", "D", "UNMAPPED"]) == {"D": 5.0}


@pytest.mark.asyncio
async def test_missing_yfinance_gives_no_prices(monkeypatch):
    monkeypatch.setitem(sys.modules, "yfinance", None)  # makes `import yfinance` raise ImportError
    assert await YahooPriceSource({"NIFTY": "^NSEI"})(["NIFTY"]) == {}
