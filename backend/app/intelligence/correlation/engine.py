"""CorrelationEngine — runs the pipeline: collect → cluster → score → filter → trend → dedupe."""
import logging
from datetime import datetime, timedelta
from typing import Any

from app.intelligence.correlation.adapters import DomainAdapter
from app.intelligence.correlation.types import SignalEvidence, ConvergenceCard

logger = logging.getLogger(__name__)


DEDUPE_TTLS: dict[str, timedelta] = {
    "default": timedelta(minutes=30),
    "silent_divergence": timedelta(hours=6),
    "explained_market_move": timedelta(hours=6),
    "polymarket_swing": timedelta(hours=2),
    "news_spike": timedelta(minutes=30),
}


class CorrelationEngine:
    """Pipeline: collect → cluster → score → filter → trend → dedupe → emit cards."""

    def __init__(self):
        self._adapters: list[DomainAdapter] = []
        self._previous_cards: dict[str, list[ConvergenceCard]] = {}
        self._dedupe_seen: dict[str, datetime] = {}

    def register_adapter(self, adapter: DomainAdapter) -> None:
        self._adapters.append(adapter)

    async def run(self, ctx: Any) -> list[ConvergenceCard]:
        all_cards: list[ConvergenceCard] = []

        for adapter in self._adapters:
            try:
                signals = await adapter.collect_signals(ctx)
            except Exception as exc:
                logger.error(f"Adapter {adapter.domain} collect_signals failed: {exc}")
                continue

            clusters = self._cluster(signals, adapter)
            scored = [(cluster, self._score_cluster(cluster, adapter)) for cluster in clusters]
            filtered = [(c, s) for c, s in scored if s >= adapter.threshold]
            cards = [self._to_card(c, s, adapter) for c, s in filtered]
            cards = self._apply_trends(cards, adapter)
            cards = self._dedupe(cards)
            self._previous_cards[adapter.domain] = cards
            all_cards.extend(cards)

        return sorted(all_cards, key=lambda c: c.score, reverse=True)

    def _cluster(self, signals: list[SignalEvidence], adapter: DomainAdapter) -> list[list[SignalEvidence]]:
        if not signals:
            return []
        cutoff = datetime.utcnow() - timedelta(hours=adapter.time_window_hours)
        recent = [s for s in signals if s.timestamp >= cutoff]

        groups: dict[str, list[SignalEvidence]] = {}
        for s in recent:
            groups.setdefault(s.market, []).append(s)

        return list(groups.values())

    def _score_cluster(self, cluster: list[SignalEvidence], adapter: DomainAdapter) -> float:
        if not cluster:
            return 0.0
        total = 0.0
        total_weight = 0.0
        for sig in cluster:
            weight = adapter.weights.get(sig.type, 0.1)
            total += sig.severity * weight
            total_weight += weight
        if total_weight <= 0:
            return 0.0
        return total / total_weight

    def _apply_trends(self, cards: list[ConvergenceCard], adapter: DomainAdapter) -> list[ConvergenceCard]:
        previous = self._previous_cards.get(adapter.domain, [])
        previous_by_id = {c.id: c for c in previous}
        out: list[ConvergenceCard] = []
        for card in cards:
            prev = previous_by_id.get(card.id)
            if prev is None:
                trend = "stable"
            elif card.score > prev.score + 5:
                trend = "escalating"
            elif card.score < prev.score - 5:
                trend = "de-escalating"
            else:
                trend = "stable"
            out.append(ConvergenceCard(
                id=card.id, domain=card.domain, title=card.title, score=card.score,
                signals=card.signals, markets=card.markets, trend=trend,
                timestamp=card.timestamp, assessment=card.assessment,
            ))
        return out

    def _dedupe(self, cards: list[ConvergenceCard]) -> list[ConvergenceCard]:
        now = datetime.utcnow()
        out: list[ConvergenceCard] = []
        for card in cards:
            key = self._dedupe_key(card)
            seen_at = self._dedupe_seen.get(key)
            ttl = DEDUPE_TTLS.get(card.domain, DEDUPE_TTLS["default"])
            if seen_at is not None and now - seen_at < ttl:
                continue
            self._dedupe_seen[key] = now
            out.append(card)
        if len(self._dedupe_seen) > 500:
            cutoff = now - timedelta(hours=24)
            self._dedupe_seen = {k: v for k, v in self._dedupe_seen.items() if v > cutoff}
        return out

    def _dedupe_key(self, card: ConvergenceCard) -> str:
        types = "+".join(sorted({s.type for s in card.signals}))
        markets = "+".join(sorted(card.markets))
        return f"{card.domain}:{markets}:{types}"

    def _to_card(self, cluster: list[SignalEvidence], score: float, adapter: DomainAdapter) -> ConvergenceCard:
        markets = sorted({s.market for s in cluster})
        types = sorted({s.type for s in cluster})
        card_id = f"{adapter.domain}:{'+'.join(markets)}:{'+'.join(types)}"
        return ConvergenceCard(
            id=card_id,
            domain=adapter.domain,
            title=adapter.generate_title(cluster),
            score=round(score, 2),
            signals=cluster,
            markets=markets,
            trend="stable",
            timestamp=datetime.utcnow(),
        )
