from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Integer, Numeric, String, UniqueConstraint
from sqlalchemy import CheckConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin


class Progress(Base, TimestampMixin):
    """Aggregated learning state per user, level, and theme."""

    __tablename__ = "progress"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    level: Mapped[str] = mapped_column(String(8), nullable=False)
    theme: Mapped[str] = mapped_column(String(255), nullable=False)
    total_answered: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_correct: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    accuracy: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False, default=0)
    streak: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_answered_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    user = relationship("User", back_populates="progress_records")

    __table_args__ = (
        UniqueConstraint("user_id", "level", "theme", name="uq_progress_user_level_theme"),
        Index("ix_progress_user_id", "user_id"),
        Index("ix_progress_level_theme", "level", "theme"),
        CheckConstraint("total_answered >= 0", name="ck_progress_total_answered_non_negative"),
        CheckConstraint("total_correct >= 0", name="ck_progress_total_correct_non_negative"),
        CheckConstraint("total_correct <= total_answered", name="ck_progress_correct_lte_answered"),
        CheckConstraint("accuracy >= 0 AND accuracy <= 100", name="ck_progress_accuracy_percent"),
        CheckConstraint("streak >= 0", name="ck_progress_streak_non_negative"),
    )
