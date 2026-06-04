from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base
from app.db.types import json_document_type


class ApiErrorLog(Base):
    """Append-only Quiz Bank API error diagnostics without sensitive payloads."""

    __tablename__ = "api_error_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[Optional[int]] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    session_id: Mapped[Optional[int]] = mapped_column(
        BigInteger,
        ForeignKey("quiz_sessions.id", ondelete="SET NULL"),
        nullable=True,
    )
    request_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    endpoint: Mapped[str] = mapped_column(String(255), nullable=False)
    status_code: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    error_category: Mapped[str] = mapped_column(String(64), nullable=False)
    level: Mapped[Optional[str]] = mapped_column(String(8), nullable=True)
    theme: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    error_metadata: Mapped[Optional[dict[str, object]]] = mapped_column("metadata", json_document_type(), nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        Index("ix_api_error_logs_occurred_at", "occurred_at"),
        Index("ix_api_error_logs_error_category", "error_category"),
        Index("ix_api_error_logs_user_id", "user_id"),
        Index("ix_api_error_logs_session_id", "session_id"),
        Index("ix_api_error_logs_request_id", "request_id"),
    )
