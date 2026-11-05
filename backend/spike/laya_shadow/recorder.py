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
        """Insert one row. False if (symbol, headline hash) is already stored.

        ``scored["dedupe_key"]`` replaces the title in that hash when titles are not unique, as with filings.
        """
        row = ShadowInference(
            symbol=symbol,
            headline=title,
            headline_hash=headline_hash(scored.get("dedupe_key") or title),
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
            url=scored.get("url"),
            doc_kind=scored.get("doc_kind"),
            body_status=scored.get("body_status"),
            body_chars=scored.get("body_chars"),
            body_hash=scored.get("body_hash"),
            body_answers=scored.get("body_answers"),
            body_latency_ms=scored.get("body_latency_ms"),
            body_tokens_read=scored.get("body_tokens_read"),
            body_tokens_dropped=scored.get("body_tokens_dropped"),
            facts=scored.get("facts"),
        )
        with self._factory() as session:
            session.add(row)
            try:
                session.commit()
            except IntegrityError:
                session.rollback()
                return False
        return True

    def exists(self, symbol: str, key: str) -> bool:
        with self._factory() as session:
            return (
                session.query(ShadowInference.id)
                .filter_by(symbol=symbol, headline_hash=headline_hash(key))
                .first()
                is not None
            )
