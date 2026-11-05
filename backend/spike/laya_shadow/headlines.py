"""Turn raw news items from any source into (title, published_at_utc)."""
import hashlib
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Optional
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
_TIME_KEYS = ("published_at", "pubDate", "seendate", "providerPublishTime")


def _parse_time(value: Any) -> Optional[datetime]:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, (int, float)):
        seconds = float(value)
        if seconds > 1e11:  # milliseconds
            seconds /= 1000
        try:
            return datetime.fromtimestamp(seconds, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    elif isinstance(value, str):
        text = value.strip()
        dt = None
        for parse in (
            lambda t: datetime.strptime(t, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc),
            lambda t: datetime.fromisoformat(t.replace("Z", "+00:00")),
            lambda t: datetime.strptime(t, "%d-%b-%Y %H:%M:%S"),
            parsedate_to_datetime,
        ):
            try:
                dt = parse(text)
                break
            except (ValueError, TypeError):
                continue
        if dt is None:
            return None
    else:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=IST)
    return dt.astimezone(timezone.utc)


def _extract_title(item: dict) -> Optional[str]:
    title = item.get("title")
    if title is None and isinstance(item.get("content"), dict):
        title = item["content"].get("title")
    if not isinstance(title, str) or not title.strip():
        return None
    title = title.strip()
    publisher = item.get("source") or item.get("publisher")
    if isinstance(publisher, str) and publisher:
        suffix = f" - {publisher}"
        if title.endswith(suffix) and len(title) > len(suffix):
            title = title[: -len(suffix)].rstrip()
    return title


def normalize_headline(item: dict) -> Optional[tuple[str, datetime]]:
    """Return (title, published_at_utc) or None if the title or publish time is unusable."""
    title = _extract_title(item)
    if title is None:
        return None
    candidates = [item.get(k) for k in _TIME_KEYS]
    if isinstance(item.get("content"), dict):
        candidates.append(item["content"].get("pubDate"))
    for value in candidates:
        published = _parse_time(value)
        if published is not None:
            return title, published
    return None


def headline_hash(title: str) -> str:
    """sha256 of the lower-cased, whitespace-collapsed title."""
    canon = re.sub(r"\s+", " ", title).strip().lower()
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()
