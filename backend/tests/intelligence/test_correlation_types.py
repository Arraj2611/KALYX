"""Tests for correlation engine types."""
import pytest
from datetime import datetime


def test_signal_evidence_creation():
    from app.intelligence.correlation.types import SignalEvidence

    sig = SignalEvidence(
        type="vix_spike",
        source="zerodha_mcp",
        severity=85.0,
        timestamp=datetime.utcnow(),
        label="VIX spiked above 18",
        market="NIFTY",
        raw={"vix": 18.5},
    )
    assert sig.type == "vix_spike"
    assert sig.severity == 85.0
    assert sig.market == "NIFTY"


def test_signal_evidence_optional_raw():
    from app.intelligence.correlation.types import SignalEvidence

    sig = SignalEvidence(
        type="news_spike", source="trafilatura", severity=50.0,
        timestamp=datetime.utcnow(), label="news event", market="BTC",
    )
    assert sig.raw is None


def test_convergence_card_creation():
    from app.intelligence.correlation.types import SignalEvidence, ConvergenceCard

    sig = SignalEvidence(
        type="vix_spike", source="zerodha_mcp", severity=85.0,
        timestamp=datetime.utcnow(), label="spike", market="NIFTY",
    )
    card = ConvergenceCard(
        id="card-001",
        domain="equity",
        title="VIX Spike + OI Buildup",
        score=78.5,
        signals=[sig],
        markets=["NIFTY"],
        trend="escalating",
        timestamp=datetime.utcnow(),
    )
    assert card.domain == "equity"
    assert card.score == 78.5
    assert card.trend == "escalating"
    assert len(card.signals) == 1
    assert card.assessment is None


def test_convergence_card_optional_assessment():
    from app.intelligence.correlation.types import ConvergenceCard

    card = ConvergenceCard(
        id="c", domain="crypto", title="t", score=60.0,
        signals=[], markets=[], trend="stable", timestamp=datetime.utcnow(),
        assessment="LLM said: be cautious",
    )
    assert card.assessment == "LLM said: be cautious"
