"""Tests for DomainAdapter implementations."""
import pytest
from datetime import datetime
from app.intelligence.correlation.types import SignalEvidence


@pytest.fixture
def stub_intel_ctx():
    class StubCtx:
        def __init__(self):
            self.symbol = "NIFTY"
            self.market_state = {"vix": 18.5, "ltp": 22500}
            self.relevant_news = [{"title": "test", "polarity": -0.6}]
            self.polymarket_odds = {"war_escalation": 0.15}
            self.geopolitical_events = []
            self.aggregated_sentiment = -0.3
    return StubCtx()


def test_domain_adapter_is_abstract():
    from app.intelligence.correlation.adapters import DomainAdapter

    with pytest.raises(TypeError):
        DomainAdapter()


def test_equity_adapter_attributes():
    from app.intelligence.correlation.adapters import EquityDomainAdapter

    adapter = EquityDomainAdapter()
    assert adapter.domain == "equity"
    assert adapter.threshold > 0
    assert adapter.time_window_hours > 0
    assert "vix_spike" in adapter.weights


def test_crypto_adapter_attributes():
    from app.intelligence.correlation.adapters import CryptoDomainAdapter

    adapter = CryptoDomainAdapter()
    assert adapter.domain == "crypto"
    assert adapter.threshold > 0


def test_forex_adapter_attributes():
    from app.intelligence.correlation.adapters import ForexDomainAdapter

    adapter = ForexDomainAdapter()
    assert adapter.domain == "forex"


def test_cross_market_adapter_attributes():
    from app.intelligence.correlation.adapters import CrossMarketAdapter

    adapter = CrossMarketAdapter()
    assert adapter.domain == "cross_market"
    assert adapter.threshold >= 70


@pytest.mark.asyncio
async def test_equity_adapter_collects_vix_spike(stub_intel_ctx):
    from app.intelligence.correlation.adapters import EquityDomainAdapter

    adapter = EquityDomainAdapter()
    signals = await adapter.collect_signals(stub_intel_ctx)
    vix_signals = [s for s in signals if s.type == "vix_spike"]
    assert len(vix_signals) >= 1


@pytest.mark.asyncio
async def test_equity_adapter_collects_news_polarity(stub_intel_ctx):
    from app.intelligence.correlation.adapters import EquityDomainAdapter

    adapter = EquityDomainAdapter()
    signals = await adapter.collect_signals(stub_intel_ctx)
    polarity_signals = [s for s in signals if s.type == "news_polarity"]
    assert len(polarity_signals) >= 1


def test_equity_adapter_generate_title():
    from app.intelligence.correlation.adapters import EquityDomainAdapter

    adapter = EquityDomainAdapter()
    sigs = [
        SignalEvidence(
            type="vix_spike", source="x", severity=80, timestamp=datetime.utcnow(),
            label="VIX spike", market="NIFTY",
        ),
    ]
    title = adapter.generate_title(sigs)
    assert isinstance(title, str)
    assert len(title) > 0
