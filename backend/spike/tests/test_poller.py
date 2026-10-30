from laya_shadow.headlines import normalize_headline
from laya_shadow.models import ShadowInference, make_session_factory
from laya_shadow.poller import GoogleNewsRss, SourceRateLimited, parse_rss, poll_once
from laya_shadow.recorder import ShadowRecorder

SYMBOLS = [{"symbol": "RELIANCE", "ticker": "RELIANCE.NS", "keywords": ["Reliance Industries"]}]
PUB = "Wed, 28 Oct 2026 04:55:35 GMT"


class FakeSource:
    def __init__(self, name, items=None, error=None):
        self.name, self.items, self.error, self.calls = name, items or [], error, []

    def fetch(self, entry):
        self.calls.append(entry)
        if self.error:
            raise self.error
        return self.items


class FakeScorer:
    def __init__(self, error=None):
        self.error, self.seen = error, []

    def score(self, headline, symbol):
        self.seen.append((headline, symbol))
        if self.error:
            raise self.error
        return {"answers": {"material": 0.5}, "latency_ms": 10.0, "model_name": "m", "model_version": "v"}


class FakeBaseline:
    def score(self, headline):
        return {"label": "positive", "score": 0.9, "polarity": 0.9}


def _run(sources, scorer=None, symbols=SYMBOLS):
    factory = make_session_factory("sqlite://")
    summary = poll_once(symbols, sources, scorer or FakeScorer(), FakeBaseline(), ShadowRecorder(factory))
    return summary, factory


def test_poll_once_records_new_headlines():
    src = FakeSource("google_rss", [{"title": "Reliance beats", "pubDate": PUB}])
    summary, factory = _run([src])
    assert summary["fetched"] == 1 and summary["recorded"] == 1
    with factory() as s:
        row = s.query(ShadowInference).one()
    assert row.source == "google_rss" and row.finbert_polarity == 0.9 and row.answers == {"material": 0.5}


def test_same_title_from_two_sources_recorded_once():
    a = FakeSource("google_rss", [{"title": "Reliance beats", "pubDate": PUB}])
    b = FakeSource("yahoo", [{"title": "reliance BEATS", "providerPublishTime": 1788169009}])
    scorer = FakeScorer()
    summary, factory = _run([a, b], scorer)
    assert summary["recorded"] == 1 and summary["duplicates"] == 1
    assert len(scorer.seen) == 1
    with factory() as s:
        assert s.query(ShadowInference).count() == 1


def test_items_without_publish_time_counted_not_recorded():
    src = FakeSource("g", [{"title": "No time"}, {"pubDate": PUB}, {"title": "Good", "pubDate": PUB}])
    summary, _ = _run([src])
    assert summary["dropped_no_time"] == 2 and summary["recorded"] == 1


def test_failing_source_does_not_stop_pass():
    bad = FakeSource("bad", error=RuntimeError("boom"))
    good = FakeSource("g", [{"title": "Reliance beats", "pubDate": PUB}])
    summary, _ = _run([bad, good])
    assert summary["errors"] == 1 and summary["recorded"] == 1


def test_scorer_exception_counted_and_pass_continues():
    src = FakeSource("g", [{"title": "One", "pubDate": PUB}, {"title": "Two", "pubDate": PUB}])
    summary, _ = _run([src], FakeScorer(error=RuntimeError("cuda oom")))
    assert summary["errors"] == 2 and summary["recorded"] == 0


def test_rate_limited_source_skipped_for_rest_of_pass():
    symbols = SYMBOLS + [{"symbol": "TCS", "ticker": "TCS.NS", "keywords": ["Tata Consultancy Services"]}]
    limited = FakeSource("gdelt", error=SourceRateLimited())
    summary, _ = _run([limited], symbols=symbols)
    assert len(limited.calls) == 1
    assert summary["errors"] == 0


def test_fetch_gets_entry_with_keywords_not_only_ticker():
    src = FakeSource("g", [])
    _run([src])
    assert src.calls[0]["keywords"] == ["Reliance Industries"] and src.calls[0]["ticker"] == "RELIANCE.NS"


RSS = b"""<?xml version="1.0"?><rss><channel>
<item><title>Reliance profit beats estimates - Economic Times</title><link>http://x/1</link>
<pubDate>Wed, 28 Oct 2026 04:55:35 GMT</pubDate><source url="http://et">Economic Times</source></item>
<item><title></title><link>http://x/2</link></item>
</channel></rss>"""


def test_google_rss_item_parsed():
    items = parse_rss(RSS)
    assert len(items) == 2 and items[0]["source"] == "Economic Times"
    title, ts = normalize_headline(items[0])
    assert title == "Reliance profit beats estimates"
    assert ts.isoformat() == "2026-10-28T04:55:35+00:00"
    assert normalize_headline(items[1]) is None


def test_google_rss_query_uses_first_keyword():
    assert "Reliance+Industries" in GoogleNewsRss.url_for({"keywords": ["Reliance Industries"]})


def test_normalize_exception_counted_not_raised(monkeypatch):
    import laya_shadow.poller as poller

    def boom(item):
        raise OSError("bad epoch")

    monkeypatch.setattr(poller, "normalize_headline", boom)
    summary, _ = _run([FakeSource("g", [{"title": "x", "pubDate": PUB}])])
    assert summary["errors"] == 1 and summary["recorded"] == 0


def test_recorder_exception_counted_and_pass_continues():
    class FlakyRecorder(ShadowRecorder):
        def record(self, *a, **k):
            raise RuntimeError("database is locked")

    factory = make_session_factory("sqlite://")
    src = FakeSource("g", [{"title": "One", "pubDate": PUB}, {"title": "Two", "pubDate": PUB}])
    summary = poll_once(SYMBOLS, [src], FakeScorer(), FakeBaseline(), FlakyRecorder(factory))
    assert summary["errors"] == 2


def test_items_per_symbol_per_source_capped():
    items = [{"title": f"Story {i}", "pubDate": PUB} for i in range(100)]
    factory = make_session_factory("sqlite://")
    summary = poll_once(SYMBOLS, [FakeSource("g", items)], FakeScorer(), FakeBaseline(), ShadowRecorder(factory), max_items=60)
    assert summary["fetched"] == 60 and summary["per_symbol"]["RELIANCE"] == 60


def test_google_query_override_used_when_present():
    url = GoogleNewsRss.url_for({"keywords": ["Adani Ports and Special Economic Zone"], "query": '"Adani Ports"'})
    assert "%22Adani+Ports%22" in url and "Special" not in url


def test_finbert_probs_stored():
    class Base2(FakeBaseline):
        def score(self, headline):
            return {"label": "positive", "score": 0.9, "polarity": 0.8, "probs": {"positive": 0.9, "neutral": 0.05, "negative": 0.05}}

    factory = make_session_factory("sqlite://")
    poll_once(SYMBOLS, [FakeSource("g", [{"title": "A", "pubDate": PUB}])], FakeScorer(), Base2(), ShadowRecorder(factory))
    with factory() as s:
        assert s.query(ShadowInference).one().finbert_probs["neutral"] == 0.05
