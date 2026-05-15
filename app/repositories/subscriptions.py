from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import and_, desc, select
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
