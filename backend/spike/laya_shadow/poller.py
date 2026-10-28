"""Poll NIFTY 50 headlines, score them with Laya and FinBERT, and store the observations.

Run:  python -m laya_shadow.poller [--once] [--interval-seconds 900] [--limit N]
"""
import argparse
import json
import logging
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Protocol

import yaml

from laya_shadow.headlines import normalize_headline
from laya_shadow.recorder import ShadowRecorder

logger = logging.getLogger("laya_shadow.poller")
_SYMBOLS_PATH = Path(__file__).resolve().parents[1] / "nifty50_symbols.yaml"


class SourceRateLimited(Exception):
    """Raised by a source that is being throttled; it is skipped for the rest of the pass."""


class NewsSource(Protocol):
    name: str

    def fetch(self, entry: dict) -> list[dict]: ...


def parse_google_rss(xml_bytes: bytes) -> list[dict]:
    items = []
    for node in ET.fromstring(xml_bytes).findall(".//item"):
        items.append(
            {
                "title": node.findtext("title"),
                "pubDate": node.findtext("pubDate"),
                "link": node.findtext("link"),
                "source": node.findtext("source"),
            }
        )
    return items


class GoogleNewsRss:
    """Primary source: public Google News RSS search, one query per company name."""

    name = "google_rss"

    @staticmethod
    def url_for(entry: dict) -> str:
        term = entry.get("query") or entry["keywords"][0]
        query = urllib.parse.urlencode({"q": f"{term} when:1d", "hl": "en-IN", "gl": "IN", "ceid": "IN:en"})
        return f"https://news.google.com/rss/search?{query}"

    def fetch(self, entry: dict) -> list[dict]:
        req = urllib.request.Request(self.url_for(entry), headers={"User-Agent": "Mozilla/5.0"})
        return parse_google_rss(urllib.request.urlopen(req, timeout=20).read())


class YahooSearchNews:
    name = "yahoo_search"

    def fetch(self, entry: dict) -> list[dict]:
        import yfinance

        return list(yfinance.Search(entry["keywords"][0], news_count=10).news or [])


class GdeltNews:
    name = "gdelt"
    _MIN_GAP_S = 10.0

    def __init__(self) -> None:
        self._last = 0.0

    def fetch(self, entry: dict) -> list[dict]:
        from gdeltdoc import Filters, GdeltDoc
        from gdeltdoc.errors import RateLimitError

        time.sleep(max(0.0, self._MIN_GAP_S - (time.monotonic() - self._last)))
        self._last = time.monotonic()
        try:
            frame = GdeltDoc().article_search(Filters(keyword=entry["keywords"][0], timespan="1d"))
        except RateLimitError as exc:
            raise SourceRateLimited() from exc
        return frame.to_dict("records") if hasattr(frame, "to_dict") else []


def load_symbols(path: Path = _SYMBOLS_PATH) -> list[dict]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


MAX_ITEMS_PER_SYMBOL = 60


def poll_once(
    symbols: list[dict], sources: list[Any], scorer: Any, baseline: Any, recorder: ShadowRecorder, max_items: int = MAX_ITEMS_PER_SYMBOL
) -> dict:
    """One pass over all symbols and sources.

    Counts: fetched items, recorded rows, duplicates (already stored), dropped_no_time (no usable
    title or publish time), errors (source, scorer or baseline failures).
    """
    counts: dict = {"fetched": 0, "recorded": 0, "duplicates": 0, "dropped_no_time": 0, "errors": 0, "per_symbol": {}}
    limited: set[str] = set()
    for entry in symbols:
        for source in sources:
            if source.name in limited:
                continue
            try:
                items = source.fetch(entry)
            except SourceRateLimited:
                logger.warning("%s rate limited; skipping it for the rest of this pass", source.name)
                limited.add(source.name)
                continue
            except Exception as exc:
                counts["errors"] += 1
                logger.warning("%s fetch failed for %s: %s", source.name, entry["symbol"], exc)
                continue
            for item in items[:max_items]:
                counts["fetched"] += 1
                try:
                    normalized = normalize_headline(item)
                    if normalized is None:
                        counts["dropped_no_time"] += 1
                        continue
                    title, published_at = normalized
                    if recorder.exists(entry["symbol"], title):
                        counts["duplicates"] += 1
                        continue
                    scored = scorer.score(title, entry["symbol"])
                    fb = baseline.score(title)
                    scored = {
                        **scored,
                        "finbert_label": fb["label"], "finbert_score": fb["score"],
                        "finbert_polarity": fb["polarity"], "finbert_probs": fb.get("probs"),
                    }
                    if recorder.record(entry["symbol"], title, published_at, source.name, scored):
                        counts["recorded"] += 1
                        counts["per_symbol"][entry["symbol"]] = counts["per_symbol"].get(entry["symbol"], 0) + 1
                    else:
                        counts["duplicates"] += 1
                except Exception as exc:  # one bad item must never stop the pass
                    counts["errors"] += 1
                    logger.warning("item failed for %s via %s: %s", entry["symbol"], source.name, exc)
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--interval-seconds", type=int, default=900)
    parser.add_argument("--limit", type=int, default=0, help="only the first N symbols (dry runs)")
    parser.add_argument("--with-yahoo", action="store_true")
    parser.add_argument("--with-gdelt", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    from laya_shadow.baseline import FinBertBaseline
    from laya_shadow.models import make_session_factory
    from laya_shadow.scorer import LayaScorer

    symbols = load_symbols()[: args.limit or None]
    sources: list[Any] = [GoogleNewsRss()]
    if args.with_yahoo:
        sources.append(YahooSearchNews())
    if args.with_gdelt:
        sources.append(GdeltNews())
    scorer, baseline = LayaScorer(), FinBertBaseline()
    recorder = ShadowRecorder(make_session_factory())
    while True:
        started = time.monotonic()
        try:
            print(json.dumps(poll_once(symbols, sources, scorer, baseline, recorder)), flush=True)
        except Exception:
            logger.exception("poll pass failed; continuing")
        if args.once:
            return
        time.sleep(max(1.0, args.interval_seconds - (time.monotonic() - started)))


if __name__ == "__main__":
    main()
