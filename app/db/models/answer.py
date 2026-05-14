from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy import UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.db.base import Base, TimestampMixin


class UserAnswer(Base, TimestampMixin):
    """Accepted user answer snapshot linked to quiz session runtime."""

    __tablename__ = "user_answers"

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
    external_quiz_id: Mapped[str] = mapped_column(String(255), nullable=False)
    selected_answer: Mapped[str] = mapped_column(Text, nullable=False)
    correct_answer: Mapped[str] = mapped_column(Text, nullable=False)
    is_correct: Mapped[bool] = mapped_column(Boolean, nullable=False)
    answered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    response_time_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    quiz_source: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    external_ref: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    user = relationship("User", back_populates="user_answers")
    session = relationship("QuizSession")

    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "session_id",
            "external_quiz_id",
            name="uq_user_answers_user_session_external_quiz",
        ),
        Index("ix_user_answers_user_id", "user_id"),
        Index("ix_user_answers_session_id", "session_id"),
        Index("ix_user_answers_external_quiz_id", "external_quiz_id"),
    )
