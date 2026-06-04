from __future__ import annotations

from datetime import datetime
from typing import Optional

import sqlalchemy as sa
from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class TrainingSessionItem(Base, TimestampMixin):
    """Question item lifecycle inside a concrete training session."""

    __tablename__ = "training_session_items"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("quiz_sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    question_reference_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("question_references.id", ondelete="RESTRICT"),
        nullable=False,
    )
    item_id: Mapped[str] = mapped_column(String(255), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="prepared",
        server_default=sa.text("'prepared'"),
    )
    shown_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    answered_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    daily_limit_id: Mapped[Optional[int]] = mapped_column(
        BigInteger,
        ForeignKey("daily_limits.id", ondelete="SET NULL"),
        nullable=True,
    )
    daily_limit_charged_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("session_id", "position", name="uq_training_session_items_session_position"),
        UniqueConstraint("session_id", "item_id", name="uq_training_session_items_session_item"),
        Index("ix_training_session_items_user_id", "user_id"),
        Index("ix_training_session_items_session_status", "session_id", "status"),
        Index("ix_training_session_items_question_reference_id", "question_reference_id"),
        Index("ix_training_session_items_daily_limit_id", "daily_limit_id"),
        CheckConstraint("position > 0", name="ck_training_session_items_position_positive"),
    )
