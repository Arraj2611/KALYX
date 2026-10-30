import json

from laya_shadow.models import ShadowInference, make_session_factory
from laya_shadow.poller import NseFilings, PublisherFeed, poll_feeds, poll_once
from laya_shadow.reader import ReadResult
from laya_shadow.recorder import ShadowRecorder
from laya_shadow.symbols import SymbolMatcher

ENTRIES = [
    {"symbol": "RELIANCE", "ticker": "RELIANCE.NS", "keywords": ["Reliance Industries"], "aliases": ["Reliance Industries", "RIL"]},
    {"symbol": "TCS", "ticker": "TCS.NS", "keywords": ["Tata Consultancy Services"], "aliases": ["TCS"]},
    {"symbol": "ITC", "ticker": "ITC.NS", "keywords": ["ITC"], "aliases": ["ITC"]},
    {"symbol": "INFY", "ticker": "INFY.NS", "keywords": ["Infosys"], "aliases": ["Infosys"]},
]
PUB = "Fri, 30 Oct 2026 04:55:35 GMT"
LINK = "https://economictimes.indiatimes.com/markets/a.cms"
SENTINEL = "This whole sentence must never be stored because it is publisher text"
BODY = f"Reliance Industries posted net profit of Rs 5,000 crore, up 18%. {SENTINEL}. " * 3
matcher = SymbolMatcher(ENTRIES)


def rss(*items):
    rows = "".join(
        f"<item><title>{title}</title><link>{link}</link><pubDate>{pub}</pubDate><description>{desc}</description></item>"
        for title, link, pub, desc in items
    )
    return f'<?xml version="1.0"?><rss><channel>{rows}</channel></rss>'.encode()


def feed(*titles):
    items = [(title, f"https://economictimes.indiatimes.com/markets/{i}.cms", PUB, "") for i, title in enumerate(titles)]
    return PublisherFeed("economic_times", "https://economictimes.indiatimes.com/rss", fetch=lambda url, cap: rss(*items))


class FakeScorer:
    def __init__(self, body_error=None):
        self.body_error, self.headlines, self.bodies = body_error, [], []

    def score(self, headline, symbol):
        self.headlines.append((headline, symbol))
        return {"answers": {"material": 0.1}, "latency_ms": 10.0, "model_name": "m", "model_version": "v"}

    def score_body(self, text, symbol):
        self.bodies.append((text, symbol))
        if self.body_error:
            raise self.body_error
        return {"answers": {"material": 0.8}, "latency_ms": 200.0, "tokens_read": 900, "tokens_dropped": 12}


class FakeBaseline:
    def score(self, headline):
        return {"label": "positive", "score": 0.9, "polarity": 0.8, "probs": {"positive": 0.9, "neutral": 0.05, "negative": 0.05}}


class FakeReader:
    def __init__(self, result=None):
        self.result, self.urls = result or ReadResult("ok", BODY), []

    def read(self, url):
        self.urls.append(url)
        return self.result


def run(feeds, scorer=None, reader=None):
    factory = make_session_factory("sqlite://")
    reader = reader or FakeReader()
    counts = poll_feeds(feeds, matcher, scorer or FakeScorer(), FakeBaseline(), ShadowRecorder(factory), reader)
    return counts, factory, reader


def only_row(factory):
    with factory() as session:
        return session.query(ShadowInference).one()


def test_article_scored_on_headline_and_full_text():
    counts, factory, _ = run([feed("Reliance Industries profit beats estimates")])
    row = only_row(factory)
    assert counts["recorded"] == 1 and counts["read_ok"] == 1
    assert row.symbol == "RELIANCE" and row.source == "economic_times" and row.doc_kind == "article"
    assert row.answers == {"material": 0.1} and row.body_answers == {"material": 0.8}
    assert row.body_status == "ok" and row.body_chars == len(BODY) and len(row.body_hash) == 64
    assert row.body_latency_ms == 200.0 and row.body_tokens_read == 900 and row.body_tokens_dropped == 12
    assert row.url.startswith("https://economictimes") and row.finbert_polarity == 0.8


def test_facts_kept_but_publisher_text_not_stored():
    _, factory, _ = run([feed("Reliance Industries profit beats estimates")])
    row = only_row(factory)
    assert [fact["value"] for fact in row.facts] == ["Rs 5,000 crore", "18%"]
    stored = json.dumps({c.name: getattr(row, c.name) for c in row.__table__.columns}, default=str)
    assert SENTINEL not in stored


def test_unmatched_article_counted_and_never_fetched():
    counts, factory, reader = run([feed("Bengaluru office rents rise")])
    assert counts["unmatched"] == 1 and counts["recorded"] == 0 and reader.urls == []


def test_market_wrap_naming_many_stocks_skipped():
    counts, _, reader = run([feed("RIL, TCS, ITC and Infosys drag Sensex lower")])
    assert counts["market_wraps"] == 1 and counts["recorded"] == 0 and reader.urls == []


def test_refused_read_keeps_headline_row_without_body():
    counts, factory, _ = run([feed("Reliance Industries profit beats")], reader=FakeReader(ReadResult("blocked")))
    row = only_row(factory)
    assert counts["recorded"] == 1 and counts["read_failed"] == 1
    assert row.body_status == "blocked" and row.body_answers is None and row.answers == {"material": 0.1}


def test_body_scoring_failure_keeps_headline_row():
    counts, factory, _ = run([feed("Reliance Industries profit beats")], scorer=FakeScorer(body_error=RuntimeError("cuda oom")))
    row = only_row(factory)
    assert counts["recorded"] == 1 and counts["errors"] == 1
    assert row.body_status == "score_failed" and row.body_answers is None


def test_article_naming_two_symbols_is_read_once_and_stored_twice():
    counts, factory, reader = run([feed("RIL and TCS lead gains")])
    assert len(reader.urls) == 1 and counts["recorded"] == 2
    with factory() as session:
        assert session.query(ShadowInference).count() == 2


def test_stored_article_is_not_read_again():
    reader, scorer = FakeReader(), FakeScorer()
    recorder = ShadowRecorder(make_session_factory("sqlite://"))
    first = poll_feeds([feed("TCS wins deal")], matcher, scorer, FakeBaseline(), recorder, reader)
    second = poll_feeds([feed("TCS wins deal")], matcher, scorer, FakeBaseline(), recorder, reader)
    assert first["recorded"] == 1 and second["duplicates"] == 1 and len(reader.urls) == 1


def test_failing_feed_does_not_stop_the_others():
    def boom(url, cap):
        raise OSError("feed down")

    broken = PublisherFeed("broken", "https://www.livemint.com/rss", fetch=boom)
    counts, _, _ = run([broken, feed("TCS wins deal")])
    assert counts["errors"] == 1 and counts["recorded"] == 1


def test_headline_from_publisher_feed_blocks_google_duplicate():
    factory = make_session_factory("sqlite://")
    recorder = ShadowRecorder(factory)
    poll_feeds([feed("TCS wins deal")], matcher, FakeScorer(), FakeBaseline(), recorder, FakeReader())

    class Google:
        name = "google_rss"

        def fetch(self, entry):
            return [{"title": "TCS wins deal", "pubDate": PUB, "link": "https://news.google.com/x"}]

    counts = poll_once(ENTRIES[1:2], [Google()], FakeScorer(), FakeBaseline(), recorder)
    assert counts["duplicates"] == 1 and counts["recorded"] == 0


def test_google_row_keeps_its_link():
    factory = make_session_factory("sqlite://")

    class Google:
        name = "google_rss"

        def fetch(self, entry):
            return [{"title": "Infosys wins deal", "pubDate": PUB, "link": "https://news.google.com/x"}]

    poll_once(ENTRIES[3:4], [Google()], FakeScorer(), FakeBaseline(), ShadowRecorder(factory))
    assert only_row(factory).url == "https://news.google.com/x"


NSE_DATE = "30-Oct-2026 21:43:08"
PDF_A = "https://nsearchives.nseindia.com/corporate/RELIANCE_1.pdf"
PDF_B = "https://nsearchives.nseindia.com/corporate/RELIANCE_2.pdf"
GENERIC = "Reliance Industries Limited has informed the Exchange about General Updates |SUBJECT: General Updates"


def filings(*items):
    return NseFilings(fetch=lambda url, cap: rss(*items))


def test_filing_mapped_by_company_name_with_description_as_headline():
    counts, factory, reader = run([filings(("Reliance Industries Limited", PDF_A, NSE_DATE, GENERIC))])
    row = only_row(factory)
    assert counts["recorded"] == 1 and reader.urls == [PDF_A]
    assert row.symbol == "RELIANCE" and row.source == "nse_filings" and row.doc_kind == "filing"
    assert row.headline == "Reliance Industries Limited has informed the Exchange about General Updates"
    assert row.url == PDF_A


def test_filing_time_read_as_ist():
    _, factory, _ = run([filings(("Reliance Industries Limited", PDF_A, NSE_DATE, GENERIC))])
    assert only_row(factory).published_at.strftime("%Y-%m-%d %H:%M:%S") == "2026-10-30 16:13:08"


def test_two_filings_with_identical_text_are_both_kept():
    counts, _, _ = run(
        [filings(("Reliance Industries Limited", PDF_A, NSE_DATE, GENERIC), ("Reliance Industries Limited", PDF_B, NSE_DATE, GENERIC))]
    )
    assert counts["recorded"] == 2


def test_filing_from_company_outside_scope_is_not_read():
    item = ("Tempsens Instruments (India) Limited", PDF_A, NSE_DATE, "Tempsens has informed the Exchange |SUBJECT: X")
    counts, _, reader = run([filings(item)])
    assert counts["unmatched"] == 1 and reader.urls == []
