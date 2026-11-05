"""Operator switches that outlive a restart and are readable by every process."""

from sqlalchemy import Boolean, Column, DateTime, String, Text
from sqlalchemy.sql import func

from app.data.database import Base


class ControlFlag(Base):
    """One row per switch. Kill-switch keys: ``halt:all`` and ``halt:account:<name>``."""

    __tablename__ = "control_flags"

    key = Column(String, primary_key=True)
    active = Column(Boolean, nullable=False, default=False)
    reason = Column(Text, nullable=True)
    updated_by = Column(String, nullable=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
