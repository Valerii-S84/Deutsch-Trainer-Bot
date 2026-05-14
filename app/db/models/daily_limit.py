from __future__ import annotations

from datetime import date, datetime

import sqlalchemy as sa
from sqlalchemy import BigInteger, CheckConstraint, Date, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class DailyLimit(Base, TimestampMixin):
    """Europe/Berlin daily question usage for a user plan."""

    __tablename__ = "daily_limits"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    plan: Mapped[str] = mapped_column(String(16), nullable=False)
    limit_date: Mapped[date] = mapped_column(Date, nullable=False)
    timezone: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default="Europe/Berlin",
        server_default=sa.text("'Europe/Berlin'"),
    )
    question_limit: Mapped[int] = mapped_column(Integer, nullable=False)
    questions_used: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=sa.text("0"))
    reset_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("user_id", "limit_date", "plan", name="uq_daily_limits_user_date_plan"),
        Index("ix_daily_limits_user_date", "user_id", "limit_date"),
        CheckConstraint("question_limit >= 0", name="ck_daily_limits_question_limit_non_negative"),
        CheckConstraint("questions_used >= 0", name="ck_daily_limits_questions_used_non_negative"),
        CheckConstraint("questions_used <= question_limit", name="ck_daily_limits_questions_used_lte_limit"),
    )
