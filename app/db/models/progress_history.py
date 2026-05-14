from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base
from app.db.types import json_document_type


class ProgressHistory(Base):
    """Append-only progress topic change event."""

    __tablename__ = "progress_history"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    progress_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("progress.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    session_id: Mapped[Optional[int]] = mapped_column(
        BigInteger,
        ForeignKey("quiz_sessions.id", ondelete="SET NULL"),
        nullable=True,
    )
    user_answer_id: Mapped[Optional[int]] = mapped_column(
        BigInteger,
        ForeignKey("user_answers.id", ondelete="SET NULL"),
        nullable=True,
    )
    level: Mapped[str] = mapped_column(String(8), nullable=False)
    theme: Mapped[str] = mapped_column(String(255), nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    previous_status: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    new_status: Mapped[str] = mapped_column(String(32), nullable=False)
    previous_scores: Mapped[Optional[dict[str, object]]] = mapped_column(json_document_type(), nullable=True)
    new_scores: Mapped[dict[str, object]] = mapped_column(json_document_type(), nullable=False)
    delta: Mapped[Optional[dict[str, object]]] = mapped_column(json_document_type(), nullable=True)
    reason_code: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        Index("ix_progress_history_user_created", "user_id", "created_at"),
        Index("ix_progress_history_progress_id", "progress_id"),
        Index("ix_progress_history_session_id", "session_id"),
        Index("ix_progress_history_user_answer_id", "user_answer_id"),
    )
