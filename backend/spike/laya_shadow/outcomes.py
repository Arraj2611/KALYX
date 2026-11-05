"""Forward returns and the materiality label.

Price series are bar *opens* indexed by bar start (tz-aware UTC), so "price at time T" is the open of
the first bar starting at or after T, provided that bar is within one bar spacing of T.
"""
from datetime import datetime, time, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

IST = ZoneInfo("Asia/Kolkata")
SESSION_OPEN = time(9, 15)
SESSION_CLOSE = time(15, 30)


def align_t0(published_at_utc: datetime) -> datetime:
    """Publish time if inside the NSE session (Mon-Fri 09:15-15:30 IST), else the next session open (UTC)."""
    ist = published_at_utc.astimezone(IST)
    if ist.weekday() < 5 and SESSION_OPEN <= ist.time() <= SESSION_CLOSE:
        return published_at_utc
    day = ist.date()
    if not (ist.weekday() < 5 and ist.time() < SESSION_OPEN):
        day += timedelta(days=1)
        while day.weekday() >= 5:
            day += timedelta(days=1)
    return datetime.combine(day, SESSION_OPEN, tzinfo=IST).astimezone(timezone.utc)


def next_session_time(t0_utc: datetime) -> datetime:
    """Same wall-clock time on the next weekday (holidays are not modelled)."""
    ist = t0_utc.astimezone(IST)
    day = ist.date() + timedelta(days=1)
    while day.weekday() >= 5:
        day += timedelta(days=1)
    return datetime.combine(day, ist.timetz()).astimezone(timezone.utc)


def _price_at(prices: pd.Series, ts: datetime, tol: pd.Timedelta) -> Optional[float]:
    pos = prices.index.searchsorted(pd.Timestamp(ts))
    if pos >= len(prices) or prices.index[pos] - pd.Timestamp(ts) > tol:
        return None
    value = float(prices.iloc[pos])
    return None if np.isnan(value) else value


def return_between(prices: pd.Series, t_from: datetime, t_to: datetime) -> Optional[float]:
    if len(prices) < 2:
        return None
    tol = prices.index.to_series().diff().median()
    p0, p1 = _price_at(prices, t_from, tol), _price_at(prices, t_to, tol)
    if p0 is None or p1 is None or p0 == 0:
        return None
    return p1 / p0 - 1


def forward_return(prices: pd.Series, t0: datetime, horizon: timedelta) -> Optional[float]:
    return return_between(prices, t0, t0 + horizon)


def adjusted_between(stock: pd.Series, index: pd.Series, t_from: datetime, t_to: datetime) -> Optional[float]:
    s, i = return_between(stock, t_from, t_to), return_between(index, t_from, t_to)
    return None if s is None or i is None else s - i


def adjusted_return(stock: pd.Series, index: pd.Series, t0: datetime, horizon: timedelta) -> Optional[float]:
    return adjusted_between(stock, index, t0, t0 + horizon)


def materiality_threshold(
    stock: pd.Series, index: pd.Series, as_of: datetime, window_days: int = 60, min_days: int = 20, min_returns: int = 50
) -> Optional[float]:
    """75th percentile of |index-adjusted 1h return| over the trading days up to ``as_of`` (unconditional)."""
    stock = stock[stock.index <= pd.Timestamp(as_of)]
    days = stock.index.normalize().unique()
    if len(days) < min_days:
        return None
    window = stock[stock.index.normalize().isin(days[-window_days:])]
    nxt = window.index + pd.Timedelta(hours=1)
    s0, s1 = window.to_numpy(), stock.reindex(nxt).to_numpy()
    i0, i1 = index.reindex(window.index).to_numpy(), index.reindex(nxt).to_numpy()
    adj = np.abs((s1 / s0 - 1) - (i1 / i0 - 1))
    adj = adj[~np.isnan(adj)]
    if len(adj) < min_returns:
        return None
    return float(np.percentile(adj, 75))
