"""IntelligenceContext + Builder.

Assembles all intelligence layer outputs into a single context object
for AnalystAgent and JudgeAgent. Cached in Redis with JSON serialization.
"""
import asyncio
import json
import logging
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Any

from app.intelligence.correlation.engine import CorrelationEngine
from app.intelligence.correlation.types import SignalEvidence, ConvergenceCard
from app.intelligence.scoring.composite import SignalQuality, compute_isq
from app.intelligence.sentiment.finbert import FinBertSentiment

logger = logging.getLogger(__name__)


@dataclass
class IntelligenceContext:
    symbol: str
    market_state: dict
    convergence_cards: list[ConvergenceCard]
    cross_market_signals: list[SignalEvidence]
    composite_score: SignalQuality | None
    relevant_news: list[dict]
    aggregated_sentiment: float
    polymarket_odds: dict[str, float]
    geopolitical_events: list[dict]
    sources_used: list[str]
    fetch_latency_ms: dict[str, float]
    built_at: datetime


class IntelligenceContextBuilder:
    """Assembles IntelligenceContext from registry + correlation + sentiment."""

    def __init__(
        self,
        registry: Any,
        correlation_engine: CorrelationEngine,
        sentiment: FinBertSentiment,
        redis_client: Any,
        cache_ttl_seconds: int = 60,
        fetch_timeout_seconds: float = 5.0,
    ):
        self._registry = registry
        self._correlation_engine = correlation_engine
        self._sentiment = sentiment
        self._redis = redis_client
        self._cache_ttl = cache_ttl_seconds
        self._fetch_timeout = fetch_timeout_seconds

    async def build(self, symbol: str, account_name: str) -> IntelligenceContext:
        cache_key = self._cache_key(symbol, account_name)
        cached = await self._get_cached(cache_key)
        if cached is not None:
            return cached

        sources_used: list[str] = []
        latency: dict[str, float] = {}

        ohlcv = await self._safe_fetch("get_ohlcv", "yfinance", sources_used, latency, symbol=symbol)
        news = await self._safe_fetch_registry("get_news", sources_used, latency, symbol=symbol)
        polymarket = await self._safe_fetch("get_polymarket_odds", "polymarket", sources_used, latency)
        geopolitical = await self._safe_fetch("get_gdelt_events", "gdelt", sources_used, latency, keyword=symbol)

        market_state = self._normalise_ohlcv(ohlcv)
        news_items = self._normalise_news(news)
        if news_items:
            try:
                scored = self._sentiment.score_batch([n.get("title", "") for n in news_items])
                for n, s in zip(news_items, scored):
                    n["polarity"] = s.get("polarity", 0)
                    n["label"] = s.get("label", "neutral")
                    n["score"] = s.get("score", 0)
                aggregated_sentiment = self._sentiment.aggregate_polarity(scored)
            except Exception as exc:
                logger.warning(f"FinBERT scoring failed: {exc}")
                aggregated_sentiment = 0.0
        else:
            aggregated_sentiment = 0.0

        polymarket_odds = polymarket if isinstance(polymarket, dict) else {}
        geopolitical_events = geopolitical if isinstance(geopolitical, list) else []

        partial_ctx = IntelligenceContext(
            symbol=symbol, market_state=market_state,
            convergence_cards=[], cross_market_signals=[],
            composite_score=None, relevant_news=news_items,
            aggregated_sentiment=aggregated_sentiment,
            polymarket_odds=polymarket_odds,
            geopolitical_events=geopolitical_events,
            sources_used=sources_used, fetch_latency_ms=latency,
            built_at=datetime.utcnow(),
        )

        cards = await self._run_correlation(partial_ctx)
        cross_market = self._extract_cross_market_signals(cards)

        composite = compute_isq(
            source_count=len(sources_used),
            is_alert=any(c.score >= 80 for c in cards),
            source_tier=1 if len(sources_used) >= 3 else 2,
            intensity_value=self._intensity_from_cards(cards),
            expectation_gap_value=abs(aggregated_sentiment),
            velocity_level="spike" if any(c.trend == "escalating" for c in cards) else "normal",
            velocity_trend="rising" if any(c.trend == "escalating" for c in cards) else None,
            profile="default",
        )

        ctx = IntelligenceContext(
            symbol=symbol, market_state=market_state,
            convergence_cards=cards, cross_market_signals=cross_market,
            composite_score=composite, relevant_news=news_items,
            aggregated_sentiment=aggregated_sentiment,
            polymarket_odds=polymarket_odds,
            geopolitical_events=geopolitical_events,
            sources_used=sources_used, fetch_latency_ms=latency,
            built_at=datetime.utcnow(),
        )

        await self._cache(cache_key, ctx)
        return ctx

    async def _safe_fetch_registry(self, method: str, sources_used, latency, **kwargs):
        """Call registry vendor chain; record the winning source name + latency."""
        start = time.perf_counter()
        try:
            result, vendor = await asyncio.wait_for(
                self._registry.fetch_with_meta(method, **kwargs),
                timeout=self._fetch_timeout,
            )
            elapsed = round((time.perf_counter() - start) * 1000, 2)
            label = vendor or method
            if vendor is not None:
                sources_used.append(vendor)
            elif result is not None:
                sources_used.append(method)
            latency[label] = elapsed
            return result
        except Exception as exc:
            elapsed = round((time.perf_counter() - start) * 1000, 2)
            latency[method] = elapsed
            logger.warning(f"safe_fetch_registry({method}) failed: {exc}")
            return None

    async def _safe_fetch(self, method, source_label, sources_used, latency, **kwargs):
        start = time.perf_counter()
        try:
            result = await asyncio.wait_for(
                self._registry.fetch(method, **kwargs),
                timeout=self._fetch_timeout,
            )
            sources_used.append(source_label)
            latency[source_label] = round((time.perf_counter() - start) * 1000, 2)
            return result
        except Exception as exc:
            latency[source_label] = round((time.perf_counter() - start) * 1000, 2)
            logger.warning(f"safe_fetch({method}) failed: {exc}")
            return None

    async def _run_correlation(self, partial_ctx):
        try:
            return await self._correlation_engine.run(partial_ctx)
        except Exception as exc:
            logger.warning(f"Correlation engine failed: {exc}")
            return []

    def _extract_cross_market_signals(self, cards):
        out = []
        for card in cards:
            if card.domain == "cross_market":
                out.extend(card.signals)
        return out

    def _intensity_from_cards(self, cards):
        if not cards:
            return 0.0
        return min(1.0, max(c.score for c in cards) / 100.0)

    def _normalise_ohlcv(self, ohlcv):
        if not ohlcv:
            return {}
        if isinstance(ohlcv, dict):
            return ohlcv
        return {}

    def _normalise_news(self, news):
        if not news:
            return []
        if isinstance(news, list):
            return [n if isinstance(n, dict) else {"title": str(n)} for n in news]
        return []

    def _cache_key(self, symbol, account_name):
        return f"intel:{account_name}:{symbol}"

    async def _get_cached(self, key):
        try:
            raw = await self._redis.get(key)
        except Exception as exc:
            logger.warning(f"Redis get failed: {exc}")
            return None
        if raw is None:
            return None
        try:
            data = json.loads(raw)
            return self._from_dict(data)
        except Exception as exc:
            logger.warning(f"Cache deserialization failed: {exc}")
            return None

    async def _cache(self, key, ctx):
        try:
            payload = json.dumps(self._to_dict(ctx))
            if hasattr(self._redis, "setex"):
                await self._redis.setex(key, self._cache_ttl, payload)
            else:
                await self._redis.set(key, payload, ex=self._cache_ttl)
        except Exception as exc:
            logger.warning(f"Cache write failed: {exc}")

    def _to_dict(self, ctx):
        return {
            "symbol": ctx.symbol,
            "market_state": ctx.market_state,
            "convergence_cards": [self._card_to_dict(c) for c in ctx.convergence_cards],
            "cross_market_signals": [self._signal_to_dict(s) for s in ctx.cross_market_signals],
            "composite_score": asdict(ctx.composite_score) if ctx.composite_score else None,
            "relevant_news": ctx.relevant_news,
            "aggregated_sentiment": ctx.aggregated_sentiment,
            "polymarket_odds": ctx.polymarket_odds,
            "geopolitical_events": ctx.geopolitical_events,
            "sources_used": ctx.sources_used,
            "fetch_latency_ms": ctx.fetch_latency_ms,
            "built_at": ctx.built_at.isoformat(),
        }

    def _from_dict(self, d):
        composite_data = d.get("composite_score")
        composite = SignalQuality(**composite_data) if composite_data else None
        return IntelligenceContext(
            symbol=d.get("symbol", ""),
            market_state=d.get("market_state", {}),
            convergence_cards=[self._dict_to_card(c) for c in d.get("convergence_cards", [])],
            cross_market_signals=[self._dict_to_signal(s) for s in d.get("cross_market_signals", [])],
            composite_score=composite,
            relevant_news=d.get("relevant_news", []),
            aggregated_sentiment=d.get("aggregated_sentiment", 0.0),
            polymarket_odds=d.get("polymarket_odds", {}),
            geopolitical_events=d.get("geopolitical_events", []),
            sources_used=d.get("sources_used", []),
            fetch_latency_ms=d.get("fetch_latency_ms", {}),
            built_at=datetime.fromisoformat(d.get("built_at", datetime.utcnow().isoformat())),
        )

    def _card_to_dict(self, card):
        return {
            "id": card.id, "domain": card.domain, "title": card.title,
            "score": card.score,
            "signals": [self._signal_to_dict(s) for s in card.signals],
            "markets": card.markets, "trend": card.trend,
            "timestamp": card.timestamp.isoformat(), "assessment": card.assessment,
        }

    def _dict_to_card(self, d):
        return ConvergenceCard(
            id=d.get("id", ""), domain=d.get("domain", ""), title=d.get("title", ""),
            score=d.get("score", 0.0),
            signals=[self._dict_to_signal(s) for s in d.get("signals", [])],
            markets=d.get("markets", []), trend=d.get("trend", "stable"),
            timestamp=datetime.fromisoformat(d.get("timestamp", datetime.utcnow().isoformat())),
            assessment=d.get("assessment"),
        )

    def _signal_to_dict(self, sig):
        return {
            "type": sig.type, "source": sig.source, "severity": sig.severity,
            "timestamp": sig.timestamp.isoformat(), "label": sig.label,
            "market": sig.market, "raw": sig.raw,
        }

    def _dict_to_signal(self, d):
        return SignalEvidence(
            type=d.get("type", ""), source=d.get("source", ""),
            severity=d.get("severity", 0.0),
            timestamp=datetime.fromisoformat(d.get("timestamp", datetime.utcnow().isoformat())),
            label=d.get("label", ""), market=d.get("market", ""), raw=d.get("raw"),
        )
