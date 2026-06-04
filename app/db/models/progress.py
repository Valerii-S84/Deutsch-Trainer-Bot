from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Integer, Numeric, String, UniqueConstraint
from sqlalchemy import CheckConstraint
import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

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
    theme_key: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    total_answered: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=sa.text("0"),
    )
    total_correct: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=sa.text("0"),
    )
    wrong_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=sa.text("0"),
    )
    accuracy: Mapped[Decimal] = mapped_column(
        Numeric(5, 2),
        nullable=False,
        default=0,
        server_default=sa.text("0"),
    )
    coverage_score: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2), nullable=True)
    coverage_status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="unknown",
        server_default=sa.text("'unknown'"),
    )
    stability_score: Mapped[Decimal] = mapped_column(
        Numeric(5, 2),
        nullable=False,
        default=0,
        server_default=sa.text("0"),
    )
    weakness_score: Mapped[Decimal] = mapped_column(
        Numeric(5, 2),
        nullable=False,
        default=0,
        server_default=sa.text("0"),
    )
    recency_score: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2), nullable=True)
    topic_status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="new",
        server_default=sa.text("'new'"),
    )
    streak: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=sa.text("0"),
    )
    unique_items_seen: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=sa.text("0"),
    )
    available_items_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    last_answered_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_wrong_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_recalculated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    user = relationship("User", back_populates="progress_records")

    __table_args__ = (
        UniqueConstraint("user_id", "level", "theme", name="uq_progress_user_level_theme"),
        Index("ix_progress_user_id", "user_id"),
        Index("ix_progress_level_theme", "level", "theme"),
        CheckConstraint("total_answered >= 0", name="ck_progress_total_answered_non_negative"),
        CheckConstraint("total_correct >= 0", name="ck_progress_total_correct_non_negative"),
        CheckConstraint("wrong_count >= 0", name="ck_progress_wrong_count_non_negative"),
        CheckConstraint("total_correct <= total_answered", name="ck_progress_correct_lte_answered"),
        CheckConstraint("total_correct + wrong_count <= total_answered", name="ck_progress_counts_lte_answered"),
        CheckConstraint("accuracy >= 0 AND accuracy <= 100", name="ck_progress_accuracy_percent"),
        CheckConstraint(
            "coverage_score IS NULL OR (coverage_score >= 0 AND coverage_score <= 100)",
            name="ck_progress_coverage_percent",
        ),
        CheckConstraint("stability_score >= 0 AND stability_score <= 100", name="ck_progress_stability_percent"),
        CheckConstraint("weakness_score >= 0 AND weakness_score <= 100", name="ck_progress_weakness_percent"),
        CheckConstraint(
            "recency_score IS NULL OR (recency_score >= 0 AND recency_score <= 100)",
            name="ck_progress_recency_percent",
        ),
        CheckConstraint("streak >= 0", name="ck_progress_streak_non_negative"),
        CheckConstraint("unique_items_seen >= 0", name="ck_progress_unique_items_non_negative"),
        CheckConstraint("available_items_count IS NULL OR available_items_count >= 0", name="ck_progress_available_non_negative"),
    )
