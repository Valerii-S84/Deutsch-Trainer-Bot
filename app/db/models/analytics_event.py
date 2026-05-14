from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.db.base import Base, TimestampMixin


class AnalyticsEvent(Base, TimestampMixin):
    """Append-only event log for analytics and operations."""

    __tablename__ = "analytics_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[Optional[int]] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    event_name: Mapped[str] = mapped_column(String(128), nullable=False)
    event_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    event_metadata: Mapped[Optional[dict[str, object]]] = mapped_column(JSONB(), nullable=True)
    session_id: Mapped[Optional[int]] = mapped_column(
        BigInteger,
        ForeignKey("quiz_sessions.id", ondelete="SET NULL"),
        nullable=True,
    )
    source: Mapped[str] = mapped_column(String(64), nullable=False)

    user = relationship("User", back_populates="analytics_events")

    __table_args__ = (
        Index("ix_analytics_events_user_id", "user_id"),
        Index("ix_analytics_events_session_id", "session_id"),
        Index("ix_analytics_events_event_name_time", "event_name", "event_time"),
    )
