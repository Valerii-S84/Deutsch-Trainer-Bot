from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base
from app.db.types import json_document_type


class MistakeHistory(Base):
    """Append-only mistake lifecycle event."""

    __tablename__ = "mistake_history"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    mistake_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("mistakes.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_answer_id: Mapped[Optional[int]] = mapped_column(
        BigInteger,
        ForeignKey("user_answers.id", ondelete="SET NULL"),
        nullable=True,
    )
    session_id: Mapped[Optional[int]] = mapped_column(
        BigInteger,
        ForeignKey("quiz_sessions.id", ondelete="SET NULL"),
        nullable=True,
    )
    item_id: Mapped[str] = mapped_column(String(255), nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    previous_status: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    new_status: Mapped[str] = mapped_column(String(32), nullable=False)
    wrong_answer: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    correct_answer: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    metadata_snapshot: Mapped[Optional[dict[str, object]]] = mapped_column(json_document_type(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        Index("ix_mistake_history_user_created", "user_id", "created_at"),
        Index("ix_mistake_history_mistake_id", "mistake_id"),
        Index("ix_mistake_history_item_id", "item_id"),
        Index("ix_mistake_history_session_id", "session_id"),
    )
