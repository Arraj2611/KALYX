"""Poll NIFTY 50 news, score it with Laya and FinBERT, and store the observations.

Publisher feeds and NSE filings are read in full. Google News adds headline coverage only: its links
do not lead to the article.

Run:  python -m laya_shadow.poller [--once] [--interval-seconds 900] [--limit N]
"""
import argparse
import hashlib
import json
import logging
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Protocol

import yaml

from laya_shadow.facts import extract_facts
from laya_shadow.headlines import normalize_headline
from laya_shadow.reader import MAX_FEED_BYTES, ArticleReader, ReadResult, fetch_bytes
from laya_shadow.recorder import ShadowRecorder
from laya_shadow.symbols import SymbolMatcher

logger = logging.getLogger("laya_shadow.poller")
_SYMBOLS_PATH = Path(__file__).resolve().parents[1] / "nifty50_symbols.yaml"
_MARKET_PATH = Path(__file__).resolve().parents[1] / "market_queries.yaml"
PUBLISHER_FEEDS = {
    "economic_times": "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms",
    "livemint": "https://www.livemint.com/rss/markets",
    "business_standard": "https://www.business-standard.com/rss/markets-106.rss",
}
NSE_ANNOUNCEMENTS_URL = "https://nsearchives.nseindia.com/content/RSS/Online_announcements.xml"
MAX_SYMBOLS_PER_ITEM = 3


class SourceRateLimited(Exception):
    """Raised by a source that is being throttled; it is skipped for the rest of the pass."""


class NewsSource(Protocol):
    name: str

    def fetch(self, entry: dict) -> list[dict]: ...


def parse_rss(xml_bytes: bytes) -> list[dict]:
    items = []
    for node in ET.fromstring(xml_bytes).findall(".//item"):
        items.append(
            {
                "title": node.findtext("title"),
                "pubDate": node.findtext("pubDate"),
                "link": node.findtext("link"),
                "source": node.findtext("source"),
                "description": node.findtext("description"),
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
        return parse_rss(urllib.request.urlopen(req, timeout=20).read())


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


class PublisherFeed:
    """A market-wide feed with direct article links. Items are matched to companies by title."""

    kind = "article"

    def __init__(self, name: str, url: str, fetch=fetch_bytes) -> None:
        self.name, self.url, self._fetch = name, url, fetch

    def fetch(self) -> list[dict]:
        return parse_rss(self._fetch(self.url, MAX_FEED_BYTES))

    def symbols(self, item: dict, matcher: SymbolMatcher) -> list[str]:
        return matcher.in_title(item.get("title") or "")


class NseFilings:
    """Official NSE announcements. The item title is only the company name, so the summary is the headline."""

    name = "nse_filings"
    kind = "filing"

    def __init__(self, fetch=fetch_bytes) -> None:
        self._fetch = fetch

    def fetch(self) -> list[dict]:
        items = parse_rss(self._fetch(NSE_ANNOUNCEMENTS_URL, MAX_FEED_BYTES))
        return [
            {
                **item,
                "company": item.get("title"),
                "title": (item.get("description") or item.get("title") or "").split(" |SUBJECT")[0].strip(),
            }
            for item in items
        ]

    def symbols(self, item: dict, matcher: SymbolMatcher) -> list[str]:
        symbol = matcher.company(item.get("company") or "")
        return [symbol] if symbol else []


def load_market_queries(path: Path = _MARKET_PATH) -> list[dict]:
    """Market-wide entries (RBI, Fed, crude, rupee, budget, the index itself) for index-level labels."""
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def load_symbols(path: Path = _SYMBOLS_PATH) -> list[dict]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


MAX_ITEMS_PER_SYMBOL = 60


def _score_headline(title: str, symbol: str, scorer: Any, baseline: Any) -> dict:
    fb = baseline.score(title)
    return {
        **scorer.score(title, symbol),
        "finbert_label": fb["label"], "finbert_score": fb["score"],
        "finbert_polarity": fb["polarity"], "finbert_probs": fb.get("probs"),
    }


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
                    scored = {**_score_headline(title, entry["symbol"], scorer, baseline), "url": item.get("link")}
                    if recorder.record(entry["symbol"], title, published_at, source.name, scored):
                        counts["recorded"] += 1
                        counts["per_symbol"][entry["symbol"]] = counts["per_symbol"].get(entry["symbol"], 0) + 1
                    else:
                        counts["duplicates"] += 1
                except Exception as exc:  # one bad item must never stop the pass
                    counts["errors"] += 1
                    logger.warning("item failed for %s via %s: %s", entry["symbol"], source.name, exc)
    return counts


def _score_document(doc: ReadResult, symbol: str, scorer: Any, counts: dict) -> dict:
    """Score the text and keep only its traces. The text itself goes no further than this function."""
    if doc.status != "ok":
        return {"body_status": doc.status}
    try:
        body = scorer.score_body(doc.text, symbol)
    except Exception as exc:
        counts["errors"] += 1
        logger.warning("full-text scoring failed for %s: %s", symbol, exc)
        return {"body_status": "score_failed"}
    return {
        "body_status": "ok",
        "body_chars": len(doc.text),
        "body_hash": hashlib.sha256(doc.text.encode("utf-8")).hexdigest(),
        "body_answers": body["answers"],
        "body_latency_ms": body["latency_ms"],
        "body_tokens_read": body["tokens_read"],
        "body_tokens_dropped": body["tokens_dropped"],
        "facts": extract_facts(doc.text),
    }


def _poll_item(feed: Any, item: dict, matcher: SymbolMatcher, scorer: Any, baseline: Any, recorder: ShadowRecorder, reader: Any, counts: dict) -> None:
    normalized = normalize_headline(item)
    if normalized is None:
        counts["dropped_no_time"] += 1
        return
    title, published_at = normalized
    symbols = feed.symbols(item, matcher)
    if not symbols:
        counts["unmatched"] += 1
        return
    if len(symbols) > MAX_SYMBOLS_PER_ITEM:
        counts["market_wraps"] += 1
        return
    link = item.get("link")
    key = link if feed.kind == "filing" and link else title
    new_symbols = [symbol for symbol in symbols if not recorder.exists(symbol, key)]
    counts["duplicates"] += len(symbols) - len(new_symbols)
    if not new_symbols:
        return
    doc = reader.read(link) if link else ReadResult("failed")
    counts["read_ok" if doc.status == "ok" else "read_failed"] += 1
    for symbol in new_symbols:
        scored = {
            **_score_headline(title, symbol, scorer, baseline),
            **_score_document(doc, symbol, scorer, counts),
            "url": link, "doc_kind": feed.kind, "dedupe_key": key,
        }
        if recorder.record(symbol, title, published_at, feed.name, scored):
            counts["recorded"] += 1
        else:
            counts["duplicates"] += 1


def poll_feeds(feeds: list[Any], matcher: SymbolMatcher, scorer: Any, baseline: Any, recorder: ShadowRecorder, reader: Any) -> dict:
    """One pass over market-wide feeds, reading every new item that names an in-scope company.

    Everything matched is read, not only high-scoring headlines: triage is what is being measured, so
    it cannot yet decide what gets read. Items naming many companies are market wraps and are skipped.
    """
    counts = dict.fromkeys(
        ("fetched", "recorded", "duplicates", "dropped_no_time", "unmatched", "market_wraps", "read_ok", "read_failed", "errors"), 0
    )
    for feed in feeds:
        try:
            items = feed.fetch()
        except Exception as exc:
            counts["errors"] += 1
            logger.warning("%s feed failed: %s", feed.name, exc)
            continue
        for item in items:
            counts["fetched"] += 1
            try:
                _poll_item(feed, item, matcher, scorer, baseline, recorder, reader, counts)
            except Exception as exc:  # one bad item must never stop the pass
                counts["errors"] += 1
                logger.warning("item failed in %s: %s", feed.name, exc)
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

    symbols = load_symbols()[: args.limit or None] + load_market_queries()
    matcher = SymbolMatcher(symbols)
    feeds: list[Any] = [PublisherFeed(name, url) for name, url in PUBLISHER_FEEDS.items()] + [NseFilings()]
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
            # Feeds first: a row with full text must win over Google's headline-only duplicate.
            read = poll_feeds(feeds, matcher, scorer, baseline, recorder, ArticleReader())
            print(json.dumps({"feeds": read, "google": poll_once(symbols, sources, scorer, baseline, recorder)}), flush=True)
        except Exception:
            logger.exception("poll pass failed; continuing")
        if args.once:
            return
        time.sleep(max(1.0, args.interval_seconds - (time.monotonic() - started)))


if __name__ == "__main__":
    main()
