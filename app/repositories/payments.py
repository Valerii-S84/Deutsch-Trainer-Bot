from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Payment


class PaymentRepository:
    """Persistence helpers for Telegram Stars payment lifecycle."""

    async def create(
        self,
        db: AsyncSession,
        *,
        user_id: int,
        plan: str,
        amount_stars: int,
        idempotency_key: str,
        config_reference: str,
        audit_metadata: dict[str, object] | None = None,
    ) -> Payment:
        payment = Payment(
            id=await self._next_id_if_needed(db),
            user_id=user_id,
            plan=plan,
            amount_stars=amount_stars,
            config_reference=config_reference,
            status="created",
            idempotency_key=idempotency_key,
            audit_metadata=audit_metadata or {},
        )
        db.add(payment)
        return payment

    async def get_by_idempotency_key(
        self,
        db: AsyncSession,
        *,
        idempotency_key: str,
    ) -> Payment | None:
        return await db.scalar(select(Payment).where(Payment.idempotency_key == idempotency_key))

    async def get_by_charge_id(
        self,
        db: AsyncSession,
        *,
        telegram_payment_charge_id: str | None,
        provider_payment_charge_id: str | None,
    ) -> Payment | None:
        clauses = []
        if telegram_payment_charge_id:
            clauses.append(Payment.telegram_payment_charge_id == telegram_payment_charge_id)
        if provider_payment_charge_id:
            clauses.append(Payment.provider_payment_charge_id == provider_payment_charge_id)
        if not clauses:
            return None
        return await db.scalar(select(Payment).where(or_(*clauses)))

    async def mark_pending(self, _db: AsyncSession, payment: Payment) -> Payment:
        if payment.status == "created":
            payment.status = "pending"
        return payment

    async def mark_paid(
        self,
        _db: AsyncSession,
        payment: Payment,
        *,
        telegram_payment_charge_id: str,
        provider_payment_charge_id: str | None,
        paid_at: datetime,
        audit_metadata: dict[str, object] | None = None,
    ) -> Payment:
        if payment.status != "credited":
            payment.status = "paid"
            payment.paid_at = paid_at
        payment.telegram_payment_charge_id = telegram_payment_charge_id
        if provider_payment_charge_id:
            payment.provider_payment_charge_id = provider_payment_charge_id
        if audit_metadata:
            payment.audit_metadata = _merge_metadata(payment.audit_metadata, audit_metadata)
        return payment

    async def mark_credited(self, _db: AsyncSession, payment: Payment, *, credited_at: datetime) -> Payment:
        payment.status = "credited"
        payment.credited_at = credited_at
        return payment

    async def mark_failed(
        self,
        _db: AsyncSession,
        payment: Payment,
        *,
        failed_at: datetime | None = None,
        reason_code: str,
    ) -> Payment:
        payment.status = "failed"
        payment.failed_at = failed_at or datetime.now(UTC)
        payment.audit_metadata = _merge_metadata(payment.audit_metadata, {"failure_reason": reason_code})
        return payment

    async def mark_cancelled(
        self,
        _db: AsyncSession,
        payment: Payment,
        *,
        cancelled_at: datetime | None = None,
        reason_code: str,
    ) -> Payment:
        payment.status = "cancelled"
        payment.cancelled_at = cancelled_at or datetime.now(UTC)
        payment.audit_metadata = _merge_metadata(payment.audit_metadata, {"cancel_reason": reason_code})
        return payment

    async def _next_id_if_needed(self, db: AsyncSession) -> int | None:
        if db.get_bind().dialect.name != "sqlite":
            return None
        max_id = await db.scalar(select(func.max(Payment.id)))
        return (max_id or 0) + 1


def _merge_metadata(existing: dict[str, Any] | None, update: dict[str, object]) -> dict[str, object]:
    metadata = dict(existing or {})
    metadata.update(update)
    return metadata
