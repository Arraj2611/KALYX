import sqlite3
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


def test_exists_true_only_after_record_for_that_symbol():
    rec, _ = _rec()
    assert rec.exists("RELIANCE", "Oil jumps") is False
    rec.record("RELIANCE", "Oil jumps", TS, "google_rss", SCORED)
    assert rec.exists("RELIANCE", "  oil JUMPS ") is True
    assert rec.exists("ONGC", "Oil jumps") is False


def test_dedupe_key_replaces_title_when_given():
    rec, factory = _rec()
    assert rec.record("RELIANCE", "Same text", TS, "nse", {**SCORED, "dedupe_key": "link-a"}) is True
    assert rec.record("RELIANCE", "Same text", TS, "nse", {**SCORED, "dedupe_key": "link-b"}) is True
    assert rec.exists("RELIANCE", "link-a") and not rec.exists("RELIANCE", "link-c")
    with factory() as s:
        assert s.query(ShadowInference).count() == 2


def test_old_database_gains_new_columns_and_keeps_its_rows(tmp_path):
    path = tmp_path / "old.db"
    connection = sqlite3.connect(path)
    connection.execute(
        "CREATE TABLE shadow_inference (id INTEGER PRIMARY KEY, observed_at DATETIME, published_at DATETIME NOT NULL, "
        "symbol VARCHAR NOT NULL, headline TEXT NOT NULL, headline_hash VARCHAR(64) NOT NULL, "
        "fill_attempts INTEGER NOT NULL DEFAULT 0, unfillable BOOLEAN NOT NULL DEFAULT 0)"
    )
    connection.execute(
        "INSERT INTO shadow_inference (published_at, symbol, headline, headline_hash) "
        "VALUES ('2026-10-28 10:00:00', 'TCS', 'old row', 'abc')"
    )
    connection.commit()
    connection.close()
    factory = make_session_factory(f"sqlite:///{path}")
    with factory() as s:
        row = s.query(ShadowInference).one()
    assert row.headline == "old row" and row.body_status is None and row.url is None and row.facts is None
    factory.kw["bind"].dispose()
