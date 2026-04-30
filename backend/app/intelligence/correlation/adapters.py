"""DomainAdapter implementations — per-market signal collectors."""
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any

from app.intelligence.correlation.types import SignalEvidence


class DomainAdapter(ABC):
    """Abstract per-market signal collector."""

    domain: str = ""
    weights: dict[str, float] = {}
    threshold: float = 50.0
    time_window_hours: int = 24

    @abstractmethod
    async def collect_signals(self, ctx: Any) -> list[SignalEvidence]: ...

    @abstractmethod
    def generate_title(self, cluster: list[SignalEvidence]) -> str: ...


class EquityDomainAdapter(DomainAdapter):
    """Detects equity-market signals: VIX spikes, OI buildups, sentiment shifts."""

    domain = "equity"
    weights = {"vix_spike": 0.4, "oi_buildup": 0.3, "news_polarity": 0.2, "rsi_extreme": 0.1}
    threshold = 60.0
    time_window_hours = 24

    async def collect_signals(self, ctx: Any) -> list[SignalEvidence]:
        signals: list[SignalEvidence] = []
        ms = getattr(ctx, "market_state", {}) or {}
        now = datetime.utcnow()

        vix = ms.get("vix")
        if vix is not None and vix > 18:
            signals.append(SignalEvidence(
                type="vix_spike", source="market_state", severity=min(100, (vix - 14) * 10),
                timestamp=now, label=f"VIX at {vix:.1f}",
                market=getattr(ctx, "symbol", ""),
                raw={"vix": vix},
            ))

        oi = ms.get("oi_change_pct")
        if oi is not None and abs(oi) > 10:
            signals.append(SignalEvidence(
                type="oi_buildup", source="market_state", severity=min(100, abs(oi) * 5),
                timestamp=now, label=f"OI change {oi:+.1f}%",
                market=getattr(ctx, "symbol", ""),
                raw={"oi_change_pct": oi},
            ))

        polarity = getattr(ctx, "aggregated_sentiment", 0.0) or 0.0
        if abs(polarity) >= 0.3:
            signals.append(SignalEvidence(
                type="news_polarity", source="finbert", severity=min(100, abs(polarity) * 100),
                timestamp=now, label=f"Aggregated polarity {polarity:+.2f}",
                market=getattr(ctx, "symbol", ""),
                raw={"polarity": polarity},
            ))

        rsi = ms.get("rsi")
        if rsi is not None and (rsi < 25 or rsi > 75):
            signals.append(SignalEvidence(
                type="rsi_extreme", source="market_state", severity=80,
                timestamp=now, label=f"RSI at {rsi:.1f}",
                market=getattr(ctx, "symbol", ""),
                raw={"rsi": rsi},
            ))

        return signals

    def generate_title(self, cluster: list[SignalEvidence]) -> str:
        types = sorted({s.type for s in cluster})
        return "Equity " + " + ".join(t.replace("_", " ").title() for t in types)


class CryptoDomainAdapter(DomainAdapter):
    domain = "crypto"
    weights = {"funding_divergence": 0.35, "dominance_shift": 0.3, "volume_spike": 0.2, "polymarket_swing": 0.15}
    threshold = 60.0
    time_window_hours = 12

    async def collect_signals(self, ctx: Any) -> list[SignalEvidence]:
        signals: list[SignalEvidence] = []
        ms = getattr(ctx, "market_state", {}) or {}
        now = datetime.utcnow()

        funding = ms.get("funding_rate")
        if funding is not None and abs(funding) > 0.01:
            signals.append(SignalEvidence(
                type="funding_divergence", source="market_state",
                severity=min(100, abs(funding) * 5000),
                timestamp=now, label=f"Funding rate {funding:+.4f}",
                market=getattr(ctx, "symbol", ""),
                raw={"funding_rate": funding},
            ))

        dominance = ms.get("btc_dominance_change_pct")
        if dominance is not None and abs(dominance) > 1:
            signals.append(SignalEvidence(
                type="dominance_shift", source="market_state",
                severity=min(100, abs(dominance) * 20),
                timestamp=now, label=f"BTC dominance {dominance:+.2f}%",
                market="BTC", raw={"dominance_pct": dominance},
            ))

        vol = ms.get("volume_zscore")
        if vol is not None and abs(vol) > 2:
            signals.append(SignalEvidence(
                type="volume_spike", source="market_state",
                severity=min(100, abs(vol) * 20),
                timestamp=now, label=f"Volume z-score {vol:+.1f}",
                market=getattr(ctx, "symbol", ""),
                raw={"volume_zscore": vol},
            ))

        return signals

    def generate_title(self, cluster: list[SignalEvidence]) -> str:
        types = sorted({s.type for s in cluster})
        return "Crypto " + " + ".join(t.replace("_", " ").title() for t in types)


class ForexDomainAdapter(DomainAdapter):
    domain = "forex"
    weights = {"polymarket_rate_swing": 0.4, "dxy_move": 0.3, "correlation_break": 0.2, "news_polarity": 0.1}
    threshold = 55.0
    time_window_hours = 12

    async def collect_signals(self, ctx: Any) -> list[SignalEvidence]:
        signals: list[SignalEvidence] = []
        ms = getattr(ctx, "market_state", {}) or {}
        polymarket = getattr(ctx, "polymarket_odds", {}) or {}
        now = datetime.utcnow()

        for key, prob in polymarket.items():
            if "rate" in key.lower() and prob > 0.7:
                signals.append(SignalEvidence(
                    type="polymarket_rate_swing", source="polymarket",
                    severity=min(100, prob * 100),
                    timestamp=now, label=f"{key} probability {prob:.0%}",
                    market="USD", raw={key: prob},
                ))

        dxy = ms.get("dxy_change_pct")
        if dxy is not None and abs(dxy) > 0.5:
            signals.append(SignalEvidence(
                type="dxy_move", source="market_state",
                severity=min(100, abs(dxy) * 50),
                timestamp=now, label=f"DXY {dxy:+.2f}%",
                market="USD", raw={"dxy_change_pct": dxy},
            ))

        return signals

    def generate_title(self, cluster: list[SignalEvidence]) -> str:
        types = sorted({s.type for s in cluster})
        return "Forex " + " + ".join(t.replace("_", " ").title() for t in types)


class CrossMarketAdapter(DomainAdapter):
    domain = "cross_market"
    weights = {
        "equity_vix": 0.25, "crypto_dump": 0.25, "forex_safe_haven": 0.20,
        "geopolitical_severity": 0.15, "polymarket_war_odds": 0.15,
    }
    threshold = 70.0
    time_window_hours = 6

    async def collect_signals(self, ctx: Any) -> list[SignalEvidence]:
        signals: list[SignalEvidence] = []
        ms = getattr(ctx, "market_state", {}) or {}
        polymarket = getattr(ctx, "polymarket_odds", {}) or {}
        geo = getattr(ctx, "geopolitical_events", []) or []
        now = datetime.utcnow()

        vix = ms.get("vix")
        if vix is not None and vix > 20:
            signals.append(SignalEvidence(
                type="equity_vix", source="market_state",
                severity=min(100, (vix - 15) * 8),
                timestamp=now, label=f"Cross-market VIX at {vix:.1f}",
                market="GLOBAL", raw={"vix": vix},
            ))

        for key, prob in polymarket.items():
            kl = key.lower()
            if any(w in kl for w in ("war", "conflict", "escalation")) and prob > 0.2:
                signals.append(SignalEvidence(
                    type="polymarket_war_odds", source="polymarket",
                    severity=min(100, prob * 200),
                    timestamp=now, label=f"{key} probability {prob:.0%}",
                    market="GLOBAL", raw={key: prob},
                ))

        if len(geo) > 0:
            severities = [e.get("severity", 0) for e in geo if isinstance(e, dict)]
            if severities:
                max_sev = max(severities)
                if max_sev > 50:
                    signals.append(SignalEvidence(
                        type="geopolitical_severity", source="gdelt",
                        severity=max_sev, timestamp=now,
                        label=f"Geopolitical event severity {max_sev}",
                        market="GLOBAL", raw={"max_severity": max_sev},
                    ))

        return signals

    def generate_title(self, cluster: list[SignalEvidence]) -> str:
        types = sorted({s.type for s in cluster})
        return "Cross-Market " + " + ".join(t.replace("_", " ").title() for t in types)
