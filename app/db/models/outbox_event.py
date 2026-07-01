from __future__ import annotations

from datetime import datetime
from typing import Optional

import sqlalchemy as sa
from sqlalchemy import BigInteger, CheckConstraint, DateTime, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base, TimestampMixin
from app.db.types import json_document_type


class OutboxEvent(Base, TimestampMixin):
    """Durable event queue for post-commit learning side effects."""

    __tablename__ = "outbox_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    event_type: Mapped[str] = mapped_column(String(128), nullable=False)
    aggregate_type: Mapped[str] = mapped_column(String(64), nullable=False)
    aggregate_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="pending",
        server_default=sa.text("'pending'"),
    )
    payload: Mapped[dict[str, object]] = mapped_column(json_document_type(), nullable=False)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=sa.text("0"))
    max_retries: Mapped[int] = mapped_column(Integer, nullable=False, default=5, server_default=sa.text("5"))
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    locked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    locked_by: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    processed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    failed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    dead_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_outbox_events_idempotency_key"),
        Index("ix_outbox_events_status_next_attempt", "status", "next_attempt_at", "id"),
        Index("ix_outbox_events_status_next_attempt_created", "status", "next_attempt_at", "created_at", "id"),
        Index("ix_outbox_events_status_locked_at", "status", "locked_at"),
        Index("ix_outbox_events_type_status", "event_type", "status"),
        Index("ix_outbox_events_aggregate", "aggregate_type", "aggregate_id"),
        CheckConstraint(
            "status IN ('pending', 'processing', 'done', 'failed', 'dead')",
            name="ck_outbox_events_status",
        ),
        CheckConstraint("retry_count >= 0", name="ck_outbox_events_retry_count_non_negative"),
        CheckConstraint("max_retries >= 0", name="ck_outbox_events_max_retries_non_negative"),
    )
