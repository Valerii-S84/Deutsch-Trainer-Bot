from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String
from sqlalchemy import CheckConstraint, Index
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.db.base import Base, TimestampMixin


class QuizSession(Base, TimestampMixin):
    """Runtime quiz session metadata without duplicating quiz bank content."""

    __tablename__ = "quiz_sessions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    level: Mapped[str] = mapped_column(String(8), nullable=False)
    theme: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="created")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    total_questions: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    correct_answers: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    source: Mapped[str] = mapped_column(String(64), nullable=False, default="quiz_bank_api")
    source_metadata: Mapped[Optional[dict[str, object]]] = mapped_column(JSONB(), nullable=True)
    api_request_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    api_metadata: Mapped[Optional[dict[str, object]]] = mapped_column(JSONB(), nullable=True)

    user = relationship("User", back_populates="quiz_sessions")

    __table_args__ = (
        Index("ix_quiz_sessions_user_id", "user_id"),
        CheckConstraint("correct_answers >= 0", name="ck_quiz_sessions_correct_answers_non_negative"),
        CheckConstraint("total_questions >= 0", name="ck_quiz_sessions_total_questions_non_negative"),
        CheckConstraint(
            "correct_answers <= total_questions",
            name="ck_quiz_sessions_correct_answers_lte_total",
        ),
    )
