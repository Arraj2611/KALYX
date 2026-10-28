from datetime import datetime, timezone

from laya_shadow.models import ShadowInference, make_session_factory
from laya_shadow.recorder import ShadowRecorder

SCORED = {
    "answers": {"material": 0.4},
    "latency_ms": 41.0,
    "model_name": "convaiinnovations/laya",
    "model_version": "abc123",
    "finbert_label": "positive",
    "finbert_score": 0.9,
    "finbert_polarity": 0.9,
}
TS = datetime(2026, 10, 28, 4, 30, tzinfo=timezone.utc)


def _rec():
    factory = make_session_factory("sqlite://")
    return ShadowRecorder(factory), factory


def test_record_inserts_row():
    rec, factory = _rec()
    assert rec.record("RELIANCE", "Reliance beats", TS, "google_rss", SCORED) is True
    with factory() as s:
        row = s.query(ShadowInference).one()
    assert row.symbol == "RELIANCE" and row.headline == "Reliance beats"
    assert row.answers == {"material": 0.4} and row.finbert_polarity == 0.9
    assert row.published_at is not None


def test_duplicate_symbol_hash_returns_false_and_stores_once():
    rec, factory = _rec()
    assert rec.record("RELIANCE", "Reliance beats", TS, "google_rss", SCORED) is True
    assert rec.record("RELIANCE", "  reliance BEATS ", TS, "yahoo", SCORED) is False
    with factory() as s:
        assert s.query(ShadowInference).count() == 1


def test_same_headline_different_symbol_stored_twice():
    rec, factory = _rec()
    assert rec.record("RELIANCE", "Oil jumps", TS, "google_rss", SCORED) is True
    assert rec.record("ONGC", "Oil jumps", TS, "google_rss", SCORED) is True
    with factory() as s:
        assert s.query(ShadowInference).count() == 2
