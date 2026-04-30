"""Types for the correlation engine. Ported from WorldMonitor correlation-engine/types.ts."""
from dataclasses import dataclass
from datetime import datetime


@dataclass
class SignalEvidence:
    """A single evidence point for a market signal."""
    type: str
    source: str
    severity: float
    timestamp: datetime
    label: str
    market: str
    raw: dict | None = None


@dataclass
class ConvergenceCard:
    """A clustered + scored set of signals indicating market convergence."""
    id: str
    domain: str
    title: str
    score: float
    signals: list[SignalEvidence]
    markets: list[str]
    trend: str
    timestamp: datetime
    assessment: str | None = None
