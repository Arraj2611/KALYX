from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest

from laya_shadow.fill import fill_pending
from laya_shadow.models import ShadowInference, make_session_factory
from laya_shadow.outcomes import (
    adjusted_return,
    align_t0,
    forward_return,
    materiality_threshold,
)

UTC = timezone.utc


def utc(y, m, d, h, mi=0):
    return datetime(y, m, d, h, mi, tzinfo=UTC)


def test_align_t0_inside_session_unchanged():  # Wed 10:30 IST
    t = utc(2026, 10, 28, 5, 0)
    assert align_t0(t) == t


def test_align_t0_after_close_moves_to_next_open():  # Wed 16:30 IST -> Thu 09:15 IST
    assert align_t0(utc(2026, 10, 28, 11, 0)) == utc(2026, 10, 29, 3, 45)


def test_align_t0_friday_evening_moves_to_monday_open():  # Fri 17:30 IST -> Mon 09:15 IST
    assert align_t0(utc(2026, 10, 30, 12, 0)) == utc(2026, 11, 2, 3, 45)


def test_align_t0_early_morning_moves_to_same_day_open():  # Wed 07:30 IST -> Wed 09:15 IST
    assert align_t0(utc(2026, 10, 28, 2, 0)) == utc(2026, 10, 28, 3, 45)


def _hourly(values, start=utc(2026, 10, 28, 3, 45)):
    idx = pd.DatetimeIndex([start + timedelta(hours=i) for i in range(len(values))])
    return pd.Series(values, index=idx, dtype=float)


def test_forward_return_basic():
    prices = _hourly([100, 101, 103, 104])
    assert forward_return(prices, utc(2026, 10, 28, 4, 45), timedelta(hours=1)) == pytest.approx(103 / 101 - 1)


def test_forward_return_missing_bar_returns_none():
    prices = _hourly([100, 101])
    assert forward_return(prices, utc(2026, 10, 28, 4, 45), timedelta(hours=1)) is None
    assert forward_return(prices, utc(2026, 10, 28, 8, 45), timedelta(hours=1)) is None


def test_adjusted_return_subtracts_index():
    stock, index = _hourly([100, 102]), _hourly([100, 101])
    t0 = utc(2026, 10, 28, 3, 45)
    assert adjusted_return(stock, index, t0, timedelta(hours=1)) == pytest.approx(0.02 - 0.01)
    assert adjusted_return(stock, _hourly([100]), t0, timedelta(hours=1)) is None


RETURNS = [0.001, 0.002, 0.003, 0.004, 0.005, 0.006]


def _history(days):
    """Business days of 7 hourly bars (09:15-15:15 IST); within a day the 1h returns cycle RETURNS."""
    stock, index = {}, {}
    day = utc(2026, 8, 3, 3, 45)
    made = 0
    while made < days:
        if day.weekday() < 5:
            price = 100.0
            for k in range(7):
                ts = day + timedelta(hours=k)
                stock[ts], index[ts] = price, 100.0
                if k < 6:
                    price *= 1 + RETURNS[k]
            made += 1
        day += timedelta(days=1)
    return pd.Series(stock), pd.Series(index), day


def test_materiality_threshold_is_75th_percentile():
    stock, index, end = _history(30)
    assert materiality_threshold(stock, index, end) == pytest.approx(np.percentile(np.tile(RETURNS, 100), 75), rel=1e-6)


def test_threshold_none_when_history_short():
    stock, index, end = _history(5)
    assert materiality_threshold(stock, index, end) is None


class FakeFetcher:
    def __init__(self, series=None):
        self.series = series or {}

    def fetch(self, ticker, interval):
        empty = pd.Series(dtype=float, index=pd.DatetimeIndex([], tz="UTC"))
        return self.series.get((ticker, interval), empty)


SYMBOLS = {"RELIANCE": {"symbol": "RELIANCE", "ticker": "RELIANCE.NS", "keywords": ["Reliance"]}}


def _row(factory, published_at, symbol="RELIANCE", headline="h"):
    with factory() as s:
        s.add(ShadowInference(symbol=symbol, headline=headline, headline_hash=headline, published_at=published_at))
        s.commit()


def _quarter_hour_day(start, prices):
    idx = pd.DatetimeIndex([start + timedelta(minutes=15 * k) for k in range(len(prices))])
    return pd.Series(prices, index=idx, dtype=float)


def _fetcher(stock_h, index_h, stock_q, index_q):
    return FakeFetcher({
        ("RELIANCE.NS", "1h"): stock_h, ("^NSEI", "1h"): index_h,
        ("RELIANCE.NS", "15m"): stock_q, ("^NSEI", "15m"): index_q,
    })


def test_fill_marks_unfillable_after_three_attempts_when_row_older_than_available_bars():
    factory = make_session_factory("sqlite://")
    _row(factory, utc(2026, 8, 3, 5, 0))
    q = _quarter_hour_day(utc(2026, 10, 27, 3, 45), [100.0] * 25)
    fetcher = _fetcher(q, q, q, q)
    now = utc(2026, 10, 28, 12, 0)
    for _ in range(3):
        fill_pending(factory, fetcher, SYMBOLS, now)
    with factory() as s:
        row = s.query(ShadowInference).one()
    assert row.fill_attempts == 3 and row.unfillable is True and row.ret_1h is None


def test_price_outage_does_not_burn_attempts():
    factory = make_session_factory("sqlite://")
    _row(factory, utc(2026, 10, 20, 5, 0))
    now = utc(2026, 10, 28, 12, 0)
    for _ in range(5):
        counts = fill_pending(factory, FakeFetcher(), SYMBOLS, now)
    with factory() as s:
        row = s.query(ShadowInference).one()
    assert row.fill_attempts == 0 and row.unfillable is False and counts["no_data"] == 1


def test_ret_1h_measured_from_fine_bars_not_next_hourly_bar():
    stock_h, index_h, end = _history(30)
    day = utc(2026, 9, 1, 3, 45)
    stock_q = _quarter_hour_day(day, [100.0 + k for k in range(25)])
    index_q = _quarter_hour_day(day, [100.0] * 25)
    factory = make_session_factory("sqlite://")
    _row(factory, utc(2026, 9, 1, 5, 10))  # 10:40 IST
    fill_pending(factory, _fetcher(stock_h, index_h, stock_q, index_q), SYMBOLS, utc(2026, 9, 3, 12, 0))
    with factory() as s:
        row = s.query(ShadowInference).one()
    assert row.ret_1h == pytest.approx(110 / 106 - 1)  # 10:45 IST bar open -> 11:45 IST bar open
    assert row.material is True  # 4.8% move vs 0.5% threshold
    assert row.off_hours is False and row.outcome_filled_at is not None


def test_off_hours_flag_set_for_after_close_headline():
    stock_h, index_h, end = _history(30)
    day = utc(2026, 9, 2, 3, 45)
    stock_q = _quarter_hour_day(day, [100.0 + k for k in range(25)])
    index_q = _quarter_hour_day(day, [100.0] * 25)
    factory = make_session_factory("sqlite://")
    _row(factory, utc(2026, 9, 1, 12, 0))  # 17:30 IST Tuesday -> aligned to Wed 09:15 IST
    fill_pending(factory, _fetcher(stock_h, index_h, stock_q, index_q), SYMBOLS, utc(2026, 9, 5, 12, 0))
    with factory() as s:
        row = s.query(ShadowInference).one()
    assert row.off_hours is True and row.ret_1h == pytest.approx(104 / 100 - 1)
