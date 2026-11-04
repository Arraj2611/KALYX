"""Fill index-adjusted forward returns and the materiality label.

Returns are measured on 15-minute bars, so the +1h window starts within 15 minutes of the headline
(1h bars could start up to 59 minutes late and miss the reaction). The materiality threshold still
uses the 1h bar distribution. Run daily (15m bars only reach back ~55 days):  python -m laya_shadow.fill
"""
import json
import logging
from datetime import datetime, time, timedelta, timezone
from typing import Callable, Protocol

import pandas as pd
from sqlalchemy.orm import Session

from laya_shadow.models import ShadowInference
from laya_shadow.outcomes import IST, adjusted_between, align_t0, materiality_threshold, next_session_time

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
    """Fill every due row. Rows are only charged an attempt when price data exists but cannot label them.

    A missing/empty series, or one that ends before t0 + 1h, is a data outage or "too early": the row is
    skipped without using up an attempt, so an outage cannot silently discard a time-clustered batch.
    """
    counts = {"filled": 0, "failed": 0, "unfillable": 0, "not_due": 0, "unknown_symbol": 0, "no_data": 0}
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
            published = _as_utc(row.published_at)
            t0 = align_t0(published)
            if t0 + timedelta(days=1, hours=1) > now:
                counts["not_due"] += 1
                continue
            ticker = entry["ticker"]
            fine, fine_idx = series(ticker, "15m"), series(INDEX_TICKER, "15m")
            hourly, hourly_idx = series(ticker, "1h"), series(INDEX_TICKER, "1h")
            if ticker == INDEX_TICKER:
                # An index entry is labeled with the raw index return: subtracting the index from itself
                # would give zero for every row. A flat series makes the adjustment a no-op.
                fine_idx = pd.Series(1.0, index=fine.index)
                hourly_idx = pd.Series(1.0, index=hourly.index)
            horizon_end = t0 + timedelta(hours=1)
            if min(len(fine), len(fine_idx), len(hourly), len(hourly_idx)) == 0 or fine.index[-1] < horizon_end:
                counts["no_data"] += 1
                continue
            row.fill_attempts += 1
            ret_1h = adjusted_between(fine, fine_idx, t0, horizon_end)
            threshold = materiality_threshold(hourly, hourly_idx, t0)
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
            row.off_hours = t0 != published
            row.ret_15m = adjusted_between(fine, fine_idx, t0, t0 + timedelta(minutes=15))
            row.ret_eod = adjusted_between(fine, fine_idx, t0, eod)
            row.ret_1d = adjusted_between(fine, fine_idx, t0, next_session_time(t0))
            row.outcome_filled_at = now
            counts["filled"] += 1
        session.commit()
    return counts


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    from laya_shadow.models import make_session_factory
    from laya_shadow.poller import load_market_queries, load_symbols

    symbols = {e["symbol"]: e for e in load_symbols() + load_market_queries()}
    print(json.dumps(fill_pending(make_session_factory(), YahooPriceFetcher(), symbols, datetime.now(timezone.utc))))


if __name__ == "__main__":
    main()
