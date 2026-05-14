from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy import CheckConstraint
import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import text
from sqlalchemy.sql import func

from app.db.base import Base, TimestampMixin
from app.db.types import json_document_type


class MistakeStatus(str, Enum):
    new = "new"
    repeated = "repeated"
    improved = "improved"
    resolved = "resolved"


class Mistake(Base, TimestampMixin):
    """Current mistake state by user and external quiz item id."""

    __tablename__ = "mistakes"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    question_reference_id: Mapped[Optional[int]] = mapped_column(
        BigInteger,
        ForeignKey("question_references.id", ondelete="SET NULL"),
        nullable=True,
    )
    external_quiz_id: Mapped[str] = mapped_column(String(255), nullable=False)
    item_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    level: Mapped[str] = mapped_column(String(8), nullable=False)
    theme: Mapped[str] = mapped_column(String(255), nullable=False)
    theme_key: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    wrong_answer: Mapped[str] = mapped_column(Text, nullable=False)
    correct_answer: Mapped[str] = mapped_column(Text, nullable=False)
    mistake_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        server_default=sa.text("1"),
    )
    successful_repeats_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=sa.text("0"),
    )
    successful_repeat_days_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=sa.text("0"),
    )
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    first_mistake_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    last_mistake_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    last_repeated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_successful_repeat_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[MistakeStatus] = mapped_column(
        String(32),
        nullable=False,
        default=MistakeStatus.new,
        server_default=sa.text("'new'"),
    )
    content_available: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=sa.text("true"))
    source_snapshot: Mapped[Optional[dict[str, object]]] = mapped_column(json_document_type(), nullable=True)

    user = relationship("User", back_populates="mistakes")

    __table_args__ = (
        Index("ix_mistakes_user_id", "user_id"),
        Index("ix_mistakes_external_quiz_id", "external_quiz_id"),
        Index("ix_mistakes_question_reference_id", "question_reference_id"),
        Index("ix_mistakes_item_id", "item_id"),
        Index(
            "ix_mistakes_active_user_external",
            "user_id",
            "external_quiz_id",
            unique=True,
            postgresql_where=text("resolved_at IS NULL"),
        ),
        CheckConstraint("mistake_count > 0", name="ck_mistakes_mistake_count_positive"),
        CheckConstraint("successful_repeats_count >= 0", name="ck_mistakes_successful_repeats_non_negative"),
        CheckConstraint("successful_repeat_days_count >= 0", name="ck_mistakes_successful_repeat_days_non_negative"),
    )
