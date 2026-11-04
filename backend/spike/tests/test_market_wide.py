"""Index-level entries: news that moves the NIFTY level, labeled with the index's own return."""

from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from laya_shadow.fill import fill_pending
from laya_shadow.models import ShadowInference, make_session_factory
from laya_shadow.poller import load_market_queries, load_symbols
from laya_shadow.scorer import build_questions
from tests.test_outcomes import FakeFetcher, _history, _quarter_hour_day, _row, utc

INDEX_ENTRY = {"symbol": "MKT_NIFTY", "ticker": "^NSEI", "keywords": ["Nifty"]}
STOCK_ENTRY = {"symbol": "RELIANCE", "ticker": "RELIANCE.NS", "keywords": ["Reliance"]}


def fetcher(history_h, quarter):
    series = {("^NSEI", "1h"): history_h, ("^NSEI", "15m"): quarter}
    return FakeFetcher(series)


def test_market_queries_load_with_everything_the_poller_needs():
    entries = load_market_queries()
    assert len(entries) >= 5
    for entry in entries:
        assert entry["symbol"].startswith("MKT_") and entry["ticker"] == "^NSEI"
        assert entry["query"] and entry["aliases"]


def test_market_aliases_never_collide_with_company_aliases():
    company = {alias for entry in load_symbols() for alias in entry["aliases"]}
    market = [alias for entry in load_market_queries() for alias in entry["aliases"]]
    assert not company & set(market)
    assert len(market) == len(set(market))


def test_index_entry_is_labeled_with_the_raw_index_return():
    history, _, _ = _history(30)
    quarter = _quarter_hour_day(utc(2026, 9, 1, 3, 45), [100.0 + k for k in range(25)])
    factory = make_session_factory("sqlite://")
    _row(factory, utc(2026, 9, 1, 5, 10), symbol="MKT_NIFTY")  # 10:40 IST

    fill_pending(factory, fetcher(history, quarter), {"MKT_NIFTY": INDEX_ENTRY}, utc(2026, 9, 3, 12, 0))

    with factory() as s:
        row = s.query(ShadowInference).one()
    assert row.ret_1h == pytest.approx(110 / 106 - 1)  # not 0, which "index minus index" would give
    assert row.material is True  # 4.7% against the index's own 75th percentile of about 0.5%
    assert row.outcome_filled_at is not None


def test_a_stock_entry_is_still_adjusted_for_the_index():
    history, index_history, _ = _history(30)
    stock_q = _quarter_hour_day(utc(2026, 9, 1, 3, 45), [100.0 + k for k in range(25)])
    index_q = _quarter_hour_day(utc(2026, 9, 1, 3, 45), [100.0] * 25)
    factory = make_session_factory("sqlite://")
    _row(factory, utc(2026, 9, 1, 5, 10))
    series = {
        ("RELIANCE.NS", "1h"): history, ("^NSEI", "1h"): index_history,
        ("RELIANCE.NS", "15m"): stock_q, ("^NSEI", "15m"): index_q,
    }

    fill_pending(factory, FakeFetcher(series), {"RELIANCE": STOCK_ENTRY}, utc(2026, 9, 3, 12, 0))

    with factory() as s:
        assert s.query(ShadowInference).one().ret_1h == pytest.approx(110 / 106 - 1)


def test_index_questions_talk_about_the_index_and_stock_wording_is_unchanged():
    index = build_questions("MKT_NIFTY")
    assert "NIFTY 50 index" in index["material_to_symbol"]["instructions"]
    assert "MKT_NIFTY" not in str(index)
    stock = build_questions("TCS")
    assert stock["material_to_symbol"]["instructions"] == "Is `message` likely to move the share price of TCS?"
    assert stock["bullish_for_symbol"]["instructions"] == "Is `message` positive news for TCS shareholders?"
    assert stock["event_type"]["instructions"] == "What kind of event does `message` describe for TCS?"
