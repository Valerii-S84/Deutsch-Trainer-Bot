from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from app.db.models import Payment, Subscription
from app.repositories.subscriptions import SubscriptionRepository
from app.services.entitlements import PLAN_FREE, PLAN_RANK

SUBSCRIPTION_CHANGE_NEW = "new_subscription"
SUBSCRIPTION_CHANGE_RENEWAL = "same_plan_renewal"
SUBSCRIPTION_CHANGE_UPGRADE = "upgrade"
SUBSCRIPTION_CHANGE_DOWNGRADE = "downgrade_forbidden"


@dataclass(frozen=True)
class SubscriptionCredit:
    subscription: Subscription
    change_type: str
    previous_plan: str
    credited_at: datetime


class SubscriptionCreditError(Exception):
    """Raised when subscription credit metadata cannot be resolved."""

    def __init__(self, reason_code: str) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


class PaymentPlanChangeError(SubscriptionCreditError):
    """Raised when a paid-plan change violates the subscription policy."""


class SubscriptionCreditPolicy:
    """Applies renewal, upgrade and downgrade business rules for paid plans."""

    def __init__(self, subscription_repo: SubscriptionRepository | None = None) -> None:
        self._subscription_repo = subscription_repo or SubscriptionRepository()

    async def ensure_plan_change_allowed(
        self,
        db,
        *,
        user_id: int,
        requested_plan: str,
        now: datetime | None = None,
    ) -> Subscription | None:
        current_subscription = await self._subscription_repo.get_effective_paid_subscription(
            db,
            user_id=user_id,
            now=now,
        )
        if _plan_change_type(current_subscription, requested_plan) == SUBSCRIPTION_CHANGE_DOWNGRADE:
            raise PaymentPlanChangeError("downgrade_not_allowed")
        return current_subscription

    async def subscription_from_credit_metadata(self, db, payment: Payment) -> Subscription:
        metadata = payment.audit_metadata or {}
        subscription_id = metadata.get("subscription_id")
        if not isinstance(subscription_id, int):
            raise SubscriptionCreditError("credited_subscription_missing")
        subscription = await self._subscription_repo.get_by_id(db, subscription_id=subscription_id)
        if subscription is None:
            raise SubscriptionCreditError("credited_subscription_missing")
        return subscription

    async def apply(
        self,
        db,
        *,
        payment: Payment,
        duration_days: int,
        credited_at: datetime,
    ) -> SubscriptionCredit:
        current_subscription = await self.ensure_plan_change_allowed(
            db,
            user_id=payment.user_id,
            requested_plan=payment.plan,
            now=credited_at,
        )
        change_type = _plan_change_type(current_subscription, payment.plan)
        if change_type == SUBSCRIPTION_CHANGE_RENEWAL:
            subscription = await self._renew_subscription(
                db,
                payment=payment,
                current_subscription=current_subscription,
                duration_days=duration_days,
                credited_at=credited_at,
            )
        elif change_type == SUBSCRIPTION_CHANGE_UPGRADE:
            subscription = await self._upgrade_subscription(
                db,
                payment=payment,
                current_subscription=current_subscription,
                duration_days=duration_days,
                started_at=credited_at,
            )
        else:
            subscription = await self._start_subscription(
                db,
                payment=payment,
                duration_days=duration_days,
                started_at=credited_at,
            )
        return SubscriptionCredit(
            subscription=subscription,
            change_type=change_type,
            previous_plan=current_subscription.plan if current_subscription is not None else PLAN_FREE,
            credited_at=credited_at,
        )

    async def _renew_subscription(
        self,
        db,
        *,
        payment: Payment,
        current_subscription: Subscription,
        duration_days: int,
        credited_at: datetime,
    ) -> Subscription:
        current_expires_at = _as_aware_utc(current_subscription.expires_at or credited_at)
        expires_at = max(current_expires_at, credited_at) + timedelta(days=duration_days)
        subscription = await self._subscription_repo.extend_current_period(
            db,
            current_subscription,
            expires_at=expires_at,
        )
        _merge_payment_audit_metadata(
            payment,
            {
                "subscription_credit_action": SUBSCRIPTION_CHANGE_RENEWAL,
                "subscription_id": subscription.id,
                "renewed_from_expires_at": current_expires_at.isoformat(),
                "renewed_to_expires_at": expires_at.isoformat(),
            },
        )
        return subscription

    async def _upgrade_subscription(
        self,
        db,
        *,
        payment: Payment,
        current_subscription: Subscription,
        duration_days: int,
        started_at: datetime,
    ) -> Subscription:
        await self._subscription_repo.close_for_upgrade(db, current_subscription, ended_at=started_at)
        return await self._start_subscription(
            db,
            payment=payment,
            duration_days=duration_days,
            started_at=started_at,
            change_type=SUBSCRIPTION_CHANGE_UPGRADE,
        )

    async def _start_subscription(
        self,
        db,
        *,
        payment: Payment,
        duration_days: int,
        started_at: datetime,
        change_type: str = SUBSCRIPTION_CHANGE_NEW,
    ) -> Subscription:
        subscription = await self._subscription_repo.create_active_from_payment(
            db,
            user_id=payment.user_id,
            plan=payment.plan,
            payment_id=payment.id,
            started_at=started_at,
            expires_at=started_at + timedelta(days=duration_days),
            provider_reference=payment.telegram_payment_charge_id or payment.provider_payment_charge_id,
        )
        _merge_payment_audit_metadata(
            payment,
            {
                "subscription_credit_action": change_type,
                "subscription_id": subscription.id,
            },
        )
        return subscription


def _plan_change_type(current_subscription: Subscription | None, requested_plan: str) -> str:
    if current_subscription is None:
        return SUBSCRIPTION_CHANGE_NEW
    current_rank = PLAN_RANK[current_subscription.plan]
    requested_rank = PLAN_RANK[requested_plan]
    if requested_rank < current_rank:
        return SUBSCRIPTION_CHANGE_DOWNGRADE
    if requested_rank == current_rank:
        return SUBSCRIPTION_CHANGE_RENEWAL
    return SUBSCRIPTION_CHANGE_UPGRADE


def _merge_payment_audit_metadata(payment: Payment, metadata: dict[str, object]) -> None:
    payment.audit_metadata = {
        **(payment.audit_metadata or {}),
        **metadata,
    }


def _as_aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
