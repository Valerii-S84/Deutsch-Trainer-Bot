from __future__ import annotations

from datetime import datetime
from typing import Optional

import sqlalchemy as sa
from sqlalchemy import BigInteger, CheckConstraint, DateTime, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base, TimestampMixin
from app.db.types import json_document_type


class QuestionReference(Base, TimestampMixin):
    """Minimal reference to an imported local catalog item."""

    __tablename__ = "question_references"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    catalog_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    item_id: Mapped[str] = mapped_column(String(255), nullable=False)
    item_version: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    level: Mapped[str] = mapped_column(String(8), nullable=False)
    theme: Mapped[str] = mapped_column(String(255), nullable=False)
    theme_key: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    source: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default="quiz_bank_api",
        server_default=sa.text("'quiz_bank_api'"),
    )
    metadata_snapshot: Mapped[Optional[dict[str, object]]] = mapped_column(json_document_type(), nullable=True)
    content_version: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    question_text_snapshot: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    correct_answer_snapshot: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    explanation_snapshot: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("catalog_id", "item_id", "item_version", name="uq_question_references_catalog_item_version"),
        Index(
            "uq_question_references_api_item_id",
            "item_id",
            unique=True,
            postgresql_where=sa.text("catalog_id IS NULL AND item_version IS NULL"),
            sqlite_where=sa.text("catalog_id IS NULL AND item_version IS NULL"),
        ),
        Index("ix_question_references_item_id", "item_id"),
        Index("ix_question_references_catalog_item", "catalog_id", "item_id"),
        Index("ix_question_references_level_theme", "level", "theme"),
        Index("ix_question_references_theme_key", "theme_key"),
        CheckConstraint("level IN ('A1', 'A2', 'B1', 'B2', 'C1')", name="ck_question_references_supported_level"),
    )
