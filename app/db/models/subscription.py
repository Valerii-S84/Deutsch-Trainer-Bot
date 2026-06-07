from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, String
from sqlalchemy import CheckConstraint, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
import sqlalchemy as sa

from app.db.base import Base, TimestampMixin


class Subscription(Base, TimestampMixin):
    """Historical and active subscription state for a user."""

    __tablename__ = "subscriptions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    plan: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="active",
        server_default=sa.text("'active'"),
    )
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    source: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default="telegram_stars",
        server_default=sa.text("'telegram_stars'"),
    )
    provider_reference: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    payment_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("payments.id"), nullable=False)

    user = relationship("User", back_populates="subscriptions")

    __table_args__ = (
        Index("ix_subscriptions_user_id", "user_id"),
        Index("ix_subscriptions_status_expires_at", "status", "expires_at"),
        UniqueConstraint("payment_id", name="uq_subscriptions_payment_id"),
        CheckConstraint("expires_at IS NULL OR started_at IS NULL OR expires_at >= started_at", name="ck_subscriptions_dates"),
    )
