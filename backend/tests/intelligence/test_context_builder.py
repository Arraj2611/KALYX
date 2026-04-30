"""Integration tests for IntelligenceContext + Builder."""
import json
import pytest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock


def test_intelligence_context_creation():
    from app.intelligence.context import IntelligenceContext

    ctx = IntelligenceContext(
        symbol="NIFTY",
        market_state={"ltp": 22500},
        convergence_cards=[],
        cross_market_signals=[],
        composite_score=None,
        relevant_news=[],
        aggregated_sentiment=0.0,
        polymarket_odds={},
        geopolitical_events=[],
        sources_used=["yfinance"],
        fetch_latency_ms={"yfinance": 50.0},
        built_at=datetime.utcnow(),
    )
    assert ctx.symbol == "NIFTY"
    assert ctx.aggregated_sentiment == 0.0


@pytest.mark.asyncio
async def test_builder_build_assembles_context():
    from app.intelligence.context import IntelligenceContextBuilder
    from app.intelligence.sentiment.finbert import FinBertSentiment
    from app.intelligence.correlation.engine import CorrelationEngine

    registry = MagicMock()
    registry.fetch = AsyncMock(side_effect=[
        {"Close": {0: 22500}},
        [{"title": "Stock surges"}],
        {"fed-rate-cut-jun": 0.82},
        [],
    ])
    sentiment = MagicMock(spec=FinBertSentiment)
    sentiment.score_batch = MagicMock(return_value=[{"polarity": 0.8, "label": "positive", "score": 0.8}])
    sentiment.aggregate_polarity = MagicMock(return_value=0.8)

    engine = CorrelationEngine()

    redis_client = MagicMock()
    redis_client.get = AsyncMock(return_value=None)
    redis_client.set = AsyncMock(return_value=True)
    redis_client.setex = AsyncMock(return_value=True)

    builder = IntelligenceContextBuilder(
        registry=registry, correlation_engine=engine,
        sentiment=sentiment, redis_client=redis_client, cache_ttl_seconds=60,
    )

    ctx = await builder.build(symbol="NIFTY", account_name="paper_test")
    assert ctx.symbol == "NIFTY"
    assert ctx.aggregated_sentiment == 0.8
    assert ctx.polymarket_odds == {"fed-rate-cut-jun": 0.82}


@pytest.mark.asyncio
async def test_builder_uses_cache_when_present():
    from app.intelligence.context import IntelligenceContextBuilder
    from app.intelligence.sentiment.finbert import FinBertSentiment
    from app.intelligence.correlation.engine import CorrelationEngine

    cached_payload = {
        "symbol": "NIFTY",
        "market_state": {"ltp": 22500},
        "convergence_cards": [],
        "cross_market_signals": [],
        "composite_score": None,
        "relevant_news": [],
        "aggregated_sentiment": 0.0,
        "polymarket_odds": {},
        "geopolitical_events": [],
        "sources_used": [],
        "fetch_latency_ms": {},
        "built_at": datetime.utcnow().isoformat(),
    }

    registry = MagicMock()
    registry.fetch = AsyncMock()
    sentiment = MagicMock(spec=FinBertSentiment)
    engine = CorrelationEngine()

    redis_client = MagicMock()
    redis_client.get = AsyncMock(return_value=json.dumps(cached_payload))
    redis_client.set = AsyncMock(return_value=True)
    redis_client.setex = AsyncMock(return_value=True)

    builder = IntelligenceContextBuilder(
        registry=registry, correlation_engine=engine,
        sentiment=sentiment, redis_client=redis_client, cache_ttl_seconds=60,
    )

    ctx = await builder.build(symbol="NIFTY", account_name="paper_test")
    assert ctx.symbol == "NIFTY"
    registry.fetch.assert_not_called()


@pytest.mark.asyncio
async def test_builder_handles_source_failure_gracefully():
    from app.intelligence.context import IntelligenceContextBuilder
    from app.intelligence.sentiment.finbert import FinBertSentiment
    from app.intelligence.correlation.engine import CorrelationEngine

    registry = MagicMock()
    registry.fetch = AsyncMock(side_effect=RuntimeError("all sources down"))
    sentiment = MagicMock(spec=FinBertSentiment)
    sentiment.score_batch = MagicMock(return_value=[])
    sentiment.aggregate_polarity = MagicMock(return_value=0.0)
    engine = CorrelationEngine()

    redis_client = MagicMock()
    redis_client.get = AsyncMock(return_value=None)
    redis_client.set = AsyncMock(return_value=True)
    redis_client.setex = AsyncMock(return_value=True)

    builder = IntelligenceContextBuilder(
        registry=registry, correlation_engine=engine,
        sentiment=sentiment, redis_client=redis_client,
    )

    ctx = await builder.build(symbol="NIFTY", account_name="paper_test")
    assert ctx.symbol == "NIFTY"
    assert ctx.market_state == {}
    assert ctx.polymarket_odds == {}
