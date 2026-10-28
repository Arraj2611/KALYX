"""Write shadow observations, deduplicated per (symbol, headline hash)."""
from datetime import datetime
from typing import Callable

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from laya_shadow.headlines import headline_hash
from laya_shadow.models import ShadowInference


class ShadowRecorder:
    def __init__(self, session_factory: Callable[[], Session]) -> None:
        self._factory = session_factory

    def record(self, symbol: str, title: str, published_at: datetime, source: str, scored: dict) -> bool:
        """Insert one row. False if (symbol, headline hash) is already stored."""
        row = ShadowInference(
            symbol=symbol,
            headline=title,
            headline_hash=headline_hash(title),
            published_at=published_at,
            source=source,
            model_name=scored.get("model_name"),
            model_version=scored.get("model_version"),
            answers=scored.get("answers"),
            latency_ms=scored.get("latency_ms"),
            finbert_label=scored.get("finbert_label"),
            finbert_score=scored.get("finbert_score"),
            finbert_polarity=scored.get("finbert_polarity"),
            finbert_probs=scored.get("finbert_probs"),
        )
        with self._factory() as session:
            session.add(row)
            try:
                session.commit()
            except IntegrityError:
                session.rollback()
                return False
        return True

    def exists(self, symbol: str, title: str) -> bool:
        with self._factory() as session:
            return (
                session.query(ShadowInference.id)
                .filter_by(symbol=symbol, headline_hash=headline_hash(title))
                .first()
                is not None
            )
