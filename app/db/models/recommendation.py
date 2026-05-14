from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin
from app.db.types import json_document_type


class Recommendation(Base, TimestampMixin):
    """Stored next learning action with German user-facing copy."""

    __tablename__ = "recommendations"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    level: Mapped[str] = mapped_column(String(8), nullable=False)
    theme: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    theme_key: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    recommendation_type: Mapped[str] = mapped_column(String(64), nullable=False)
    reason_code: Mapped[str] = mapped_column(String(64), nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False)
    copy_de: Mapped[str] = mapped_column(Text, nullable=False)
    source_snapshot: Mapped[Optional[dict[str, object]]] = mapped_column(json_document_type(), nullable=True)
    shown_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    acted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_recommendations_user_priority", "user_id", "priority"),
        Index("ix_recommendations_user_created", "user_id", "created_at"),
        CheckConstraint("priority >= 0", name="ck_recommendations_priority_non_negative"),
    )
