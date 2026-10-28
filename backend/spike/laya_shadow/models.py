"""shadow_inference table (SQLite by default, own file; never the app's Postgres)."""
import os
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from sqlalchemy import JSON, event, Boolean, DateTime, Float, Integer, String, Text, UniqueConstraint, create_engine, func
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker
from sqlalchemy.pool import StaticPool

_DEFAULT_DB = Path(__file__).resolve().parents[1] / "shadow.db"


class Base(DeclarativeBase):
    pass


class ShadowInference(Base):
    """One Laya + FinBERT observation of one headline for one symbol.

    SQLite does not keep time zones: datetimes read back are naive UTC.
    """

    __tablename__ = "shadow_inference"
    __table_args__ = (UniqueConstraint("symbol", "headline_hash", name="uq_symbol_headline"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    symbol: Mapped[str] = mapped_column(String, nullable=False, index=True)
    headline: Mapped[str] = mapped_column(Text, nullable=False)
    headline_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    source: Mapped[Optional[str]] = mapped_column(String)
    model_name: Mapped[Optional[str]] = mapped_column(String)
    model_version: Mapped[Optional[str]] = mapped_column(String)
    answers: Mapped[Optional[dict]] = mapped_column(JSON)
    latency_ms: Mapped[Optional[float]] = mapped_column(Float)
    finbert_label: Mapped[Optional[str]] = mapped_column(String)
    finbert_score: Mapped[Optional[float]] = mapped_column(Float)
    finbert_polarity: Mapped[Optional[float]] = mapped_column(Float)
    finbert_probs: Mapped[Optional[dict]] = mapped_column(JSON)
    ret_15m: Mapped[Optional[float]] = mapped_column(Float)
    ret_1h: Mapped[Optional[float]] = mapped_column(Float)
    ret_eod: Mapped[Optional[float]] = mapped_column(Float)
    ret_1d: Mapped[Optional[float]] = mapped_column(Float)
    material: Mapped[Optional[bool]] = mapped_column(Boolean)
    off_hours: Mapped[Optional[bool]] = mapped_column(Boolean)
    fill_attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    unfillable: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    outcome_filled_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


def make_session_factory(url: Optional[str] = None) -> Callable[[], Session]:
    """Create tables if missing and return a session factory.

    URL order: argument, then SHADOW_DB_URL, then backend/spike/shadow.db.
    """
    url = url or os.environ.get("SHADOW_DB_URL") or f"sqlite:///{_DEFAULT_DB}"
    kwargs = {}
    if url in ("sqlite://", "sqlite:///:memory:"):
        kwargs = {"connect_args": {"check_same_thread": False}, "poolclass": StaticPool}
    elif url.startswith("sqlite"):
        kwargs = {"connect_args": {"timeout": 30}}
    engine = create_engine(url, **kwargs)
    if url.startswith("sqlite") and url not in ("sqlite://", "sqlite:///:memory:"):

        @event.listens_for(engine, "connect")
        def _wal(dbapi_connection, _record):  # concurrent poller + fill
            dbapi_connection.execute("PRAGMA journal_mode=WAL")

    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)
