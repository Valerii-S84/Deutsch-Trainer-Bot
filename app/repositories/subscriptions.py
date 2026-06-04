from __future__ import annotations

from datetime import UTC, datetime

from datetime import datetime

from sqlalchemy import and_, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Payment, Subscription

PAID_PLANS = {"plus", "pro"}


class SubscriptionRepository:
    """Read helpers for effective subscription access."""

    async def get_effective_paid_subscription(
        self,
        db: AsyncSession,
        *,
        user_id: int,
        now: datetime | None = None,
    ) -> Subscription | None:
        current_time = now or datetime.now(UTC)
        query = (
            select(Subscription)
            .join(Payment, Payment.id == Subscription.payment_id)
            .where(
                Subscription.user_id == user_id,
                Subscription.status == "active",
                Subscription.plan.in_(PAID_PLANS),
                Payment.credited_at.is_not(None),
                Payment.status == "credited",
                and_(
                    Subscription.expires_at.is_not(None),
                    Subscription.expires_at > current_time,
                ),
            )
            .order_by(desc(Subscription.expires_at), desc(Subscription.id))
        )
        return await db.scalar(query)

    async def get_latest_for_user(
        self,
        db: AsyncSession,
        *,
        user_id: int,
    ) -> Subscription | None:
        query = (
            select(Subscription)
            .where(Subscription.user_id == user_id)
            .order_by(desc(Subscription.created_at), desc(Subscription.id))
            .limit(1)
        )
        return await db.scalar(query)

    async def get_by_payment_id(
        self,
        db: AsyncSession,
        *,
        payment_id: int,
    ) -> Subscription | None:
        return await db.scalar(select(Subscription).where(Subscription.payment_id == payment_id))

    async def create_active_from_payment(
        self,
        db: AsyncSession,
        *,
        user_id: int,
        plan: str,
        payment_id: int,
        started_at: datetime,
        expires_at: datetime,
        provider_reference: str | None,
    ) -> Subscription:
        subscription = Subscription(
            id=await self._next_id_if_needed(db),
            user_id=user_id,
            plan=plan,
            status="active",
            started_at=started_at,
            expires_at=expires_at,
            source="telegram_stars",
            provider_reference=provider_reference,
            payment_id=payment_id,
        )
        db.add(subscription)
        return subscription

    async def list_user_subscriptions(
        self,
        db: AsyncSession,
        *,
        user_id: int,
    ) -> list[Subscription]:
        query = (
            select(Subscription)
            .where(Subscription.user_id == user_id)
            .order_by(desc(Subscription.created_at), desc(Subscription.id))
        )
        result = await db.execute(query)
        return list(result.scalars().all())

    async def _next_id_if_needed(self, db: AsyncSession) -> int | None:
        if db.get_bind().dialect.name != "sqlite":
            return None
        max_id = await db.scalar(select(func.max(Subscription.id)))
        return (max_id or 0) + 1
