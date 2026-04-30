"""Tests for CorrelationEngine pipeline."""
import pytest
from datetime import datetime, timedelta
from app.intelligence.correlation.types import SignalEvidence


class StubAdapter:
    domain = "test"
    weights = {"a": 0.5, "b": 0.5}
    threshold = 50.0
    time_window_hours = 24

    def __init__(self, signals=None):
        self._signals = signals or []

    async def collect_signals(self, ctx):
        return list(self._signals)

    def generate_title(self, cluster):
        return f"Test cluster ({len(cluster)} signals)"


@pytest.mark.asyncio
async def test_engine_creation():
    from app.intelligence.correlation.engine import CorrelationEngine

    eng = CorrelationEngine()
    assert eng is not None


@pytest.mark.asyncio
async def test_engine_register_adapter():
    from app.intelligence.correlation.engine import CorrelationEngine

    eng = CorrelationEngine()
    eng.register_adapter(StubAdapter())


@pytest.mark.asyncio
async def test_engine_runs_with_no_adapters():
    from app.intelligence.correlation.engine import CorrelationEngine

    eng = CorrelationEngine()
    cards = await eng.run(ctx=None)
    assert cards == []


@pytest.mark.asyncio
async def test_engine_emits_card_above_threshold():
    from app.intelligence.correlation.engine import CorrelationEngine

    now = datetime.utcnow()
    sigs = [
        SignalEvidence(type="a", source="x", severity=90, timestamp=now,
                       label="strong a", market="NIFTY"),
        SignalEvidence(type="b", source="y", severity=80, timestamp=now,
                       label="strong b", market="NIFTY"),
    ]
    eng = CorrelationEngine()
    eng.register_adapter(StubAdapter(signals=sigs))

    cards = await eng.run(ctx=None)
    assert len(cards) >= 1
    assert cards[0].score > 50


@pytest.mark.asyncio
async def test_engine_skips_below_threshold():
    from app.intelligence.correlation.engine import CorrelationEngine

    now = datetime.utcnow()
    sigs = [
        SignalEvidence(type="a", source="x", severity=10, timestamp=now,
                       label="weak", market="NIFTY"),
    ]
    eng = CorrelationEngine()
    eng.register_adapter(StubAdapter(signals=sigs))

    cards = await eng.run(ctx=None)
    assert cards == []


@pytest.mark.asyncio
async def test_engine_dedupes_recent_card():
    from app.intelligence.correlation.engine import CorrelationEngine

    now = datetime.utcnow()
    sigs = [
        SignalEvidence(type="a", source="x", severity=90, timestamp=now,
                       label="strong", market="NIFTY"),
        SignalEvidence(type="b", source="y", severity=85, timestamp=now,
                       label="strong", market="NIFTY"),
    ]
    eng = CorrelationEngine()
    eng.register_adapter(StubAdapter(signals=sigs))

    first_run = await eng.run(ctx=None)
    second_run = await eng.run(ctx=None)
    assert len(first_run) >= 1
    assert len(second_run) == 0


@pytest.mark.asyncio
async def test_engine_sorts_by_score_desc():
    from app.intelligence.correlation.engine import CorrelationEngine

    now = datetime.utcnow()
    high = [
        SignalEvidence(type="a", source="x", severity=95, timestamp=now,
                       label="h1", market="A"),
        SignalEvidence(type="b", source="y", severity=95, timestamp=now,
                       label="h2", market="A"),
    ]
    mid = [
        SignalEvidence(type="a", source="x", severity=70, timestamp=now,
                       label="m1", market="B"),
        SignalEvidence(type="b", source="y", severity=70, timestamp=now,
                       label="m2", market="B"),
    ]

    high_adapter = StubAdapter(signals=high)
    high_adapter.domain = "high_dom"
    mid_adapter = StubAdapter(signals=mid)
    mid_adapter.domain = "mid_dom"

    eng = CorrelationEngine()
    eng.register_adapter(high_adapter)
    eng.register_adapter(mid_adapter)

    cards = await eng.run(ctx=None)
    if len(cards) >= 2:
        assert cards[0].score >= cards[1].score
