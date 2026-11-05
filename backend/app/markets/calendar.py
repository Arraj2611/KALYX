"""Exchange trading sessions.

Weekends and the hours of each session are built in. Holidays are data: they are read from
``config/market_holidays.yaml`` and must be copied from the exchange's own holiday circular.
A weekday holiday that is not listed looks like an open day to this module.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Optional
from zoneinfo import ZoneInfo

import yaml

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Session:
    tz: str
    open: time
    close: time
    weekdays: tuple[int, ...] = (0, 1, 2, 3, 4)  # Monday = 0


SESSIONS: dict[str, Session] = {
    "NSE": Session("Asia/Kolkata", time(9, 15), time(15, 30)),
    "NYSE": Session("America/New_York", time(9, 30), time(16, 0)),
}


class MarketCalendar:
    def __init__(self, holidays: Optional[dict[str, set[date]]] = None) -> None:
        self._holidays = holidays or {}

    def is_open(self, exchange: str, when: datetime) -> bool:
        """True from the opening time up to, but not including, the closing time, on a trading day."""
        if when.tzinfo is None:
            raise ValueError("is_open needs a timezone-aware datetime")
        session = SESSIONS.get(exchange)
        if session is None:
            raise ValueError(f"Unknown exchange '{exchange}'; known: {sorted(SESSIONS)}")
        local = when.astimezone(ZoneInfo(session.tz))
        if local.weekday() not in session.weekdays:
            return False
        if local.date() in self._holidays.get(exchange, set()):
            return False
        return session.open <= local.time() < session.close


def load_holidays(path: str) -> dict[str, set[date]]:
    """Read ``{EXCHANGE: [ISO dates]}``. A missing file is an empty calendar, with a warning."""
    if not os.path.exists(path):
        logger.warning("No holiday file at %s: only weekends are treated as closed", path)
        return {}
    with open(path, "r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}
    return {
        exchange: {date.fromisoformat(str(day)) for day in (days or [])}
        for exchange, days in raw.items()
    }
