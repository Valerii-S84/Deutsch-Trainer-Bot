from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, Index, String
from sqlalchemy import CheckConstraint, UniqueConstraint
import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin
from app.db.types import json_document_type


class Payment(Base, TimestampMixin):
    """Raw payment + crediting record for subscription plans."""

    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    telegram_payment_charge_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    provider_payment_charge_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    plan: Mapped[str] = mapped_column(String(16), nullable=False)
    amount_stars: Mapped[int] = mapped_column(Integer, nullable=False)
    config_reference: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="created",
        server_default=sa.text("'created'"),
    )
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    paid_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    credited_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    failed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    source: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default="telegram_stars",
        server_default=sa.text("'telegram_stars'"),
    )
    audit_metadata: Mapped[Optional[dict[str, object]]] = mapped_column(json_document_type(), nullable=True)

    user = relationship("User", back_populates="payments")

    __table_args__ = (
        Index("ix_payments_user_id", "user_id"),
        UniqueConstraint("idempotency_key", name="uq_payments_idempotency_key"),
        UniqueConstraint("telegram_payment_charge_id", name="uq_payments_telegram_payment_charge_id"),
        UniqueConstraint("provider_payment_charge_id", name="uq_payments_provider_payment_charge_id"),
        CheckConstraint("amount_stars >= 0", name="ck_payments_amount_stars_non_negative"),
        CheckConstraint(
            "status NOT IN ('paid', 'credited') "
            "OR (telegram_payment_charge_id IS NOT NULL AND trim(telegram_payment_charge_id) <> '')",
            name="ck_payments_confirmed_telegram_charge_id",
        ),
    )
