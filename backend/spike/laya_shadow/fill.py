"""Fill index-adjusted forward returns and the materiality label.

Run daily:  python -m laya_shadow.fill
"""
import json
import logging
from datetime import datetime, time, timedelta, timezone
from typing import Callable, Optional, Protocol

import pandas as pd
from sqlalchemy.orm import Session

from laya_shadow.models import ShadowInference
from laya_shadow.outcomes import IST, adjusted_between, adjusted_return, align_t0, materiality_threshold, next_session_time

logger = logging.getLogger("laya_shadow.fill")
INDEX_TICKER = "^NSEI"
MAX_ATTEMPTS = 3


class PriceFetcher(Protocol):
    def fetch(self, ticker: str, interval: str) -> pd.Series: ...


class YahooPriceFetcher:
    """Bar opens from yfinance, UTC-indexed. 1h goes back ~180 days, 15m ~55 days."""

    _PERIOD = {"1h": "180d", "15m": "55d"}

    def fetch(self, ticker: str, interval: str) -> pd.Series:
        import yfinance

        try:
            frame = yfinance.Ticker(ticker).history(period=self._PERIOD[interval], interval=interval)
        except Exception as exc:
            logger.warning("price fetch failed for %s %s: %s", ticker, interval, exc)
            frame = None
        if frame is None or frame.empty:
            return pd.Series(dtype=float, index=pd.DatetimeIndex([], tz="UTC"))
        series = frame["Open"].dropna()
        series.index = series.index.tz_convert("UTC")
        return series.sort_index()


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def fill_pending(session_factory: Callable[[], Session], fetcher: PriceFetcher, symbols: dict, now: datetime) -> dict:
    counts = {"filled": 0, "failed": 0, "unfillable": 0, "not_due": 0, "unknown_symbol": 0}
    cache: dict[tuple[str, str], pd.Series] = {}

    def series(ticker: str, interval: str) -> pd.Series:
        if (ticker, interval) not in cache:
            cache[(ticker, interval)] = fetcher.fetch(ticker, interval)
        return cache[(ticker, interval)]

    with session_factory() as session:
        rows = (
            session.query(ShadowInference)
            .filter(ShadowInference.outcome_filled_at.is_(None), ShadowInference.unfillable.is_(False))
            .all()
        )
        for row in rows:
            entry = symbols.get(row.symbol)
            if entry is None:
                counts["unknown_symbol"] += 1
                continue
            t0 = align_t0(_as_utc(row.published_at))
            if t0 + timedelta(days=1, hours=1) > now:
                counts["not_due"] += 1
                continue
            hourly, index_h = series(entry["ticker"], "1h"), series(INDEX_TICKER, "1h")
            ret_1h = adjusted_return(hourly, index_h, t0, timedelta(hours=1))
            threshold = materiality_threshold(hourly, index_h, t0)
            row.fill_attempts += 1
            if ret_1h is None or threshold is None:
                if row.fill_attempts >= MAX_ATTEMPTS:
                    row.unfillable = True
                    counts["unfillable"] += 1
                else:
                    counts["failed"] += 1
                continue
            eod = datetime.combine(t0.astimezone(IST).date(), time(15, 15), tzinfo=IST).astimezone(timezone.utc)
            row.ret_1h = ret_1h
            row.material = abs(ret_1h) > threshold
            row.ret_15m = adjusted_return(series(entry["ticker"], "15m"), series(INDEX_TICKER, "15m"), t0, timedelta(minutes=15))
            row.ret_eod = adjusted_between(hourly, index_h, t0, eod)
            row.ret_1d = adjusted_between(hourly, index_h, t0, next_session_time(t0))
            row.outcome_filled_at = now
            counts["filled"] += 1
        session.commit()
    return counts


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    from laya_shadow.models import make_session_factory
    from laya_shadow.poller import load_symbols

    symbols = {e["symbol"]: e for e in load_symbols()}
    print(json.dumps(fill_pending(make_session_factory(), YahooPriceFetcher(), symbols, datetime.now(timezone.utc))))


if __name__ == "__main__":
    main()
