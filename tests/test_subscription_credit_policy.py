from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.db.models import Payment, Subscription
from app.services.entitlements import PLAN_FREE, PLAN_PLUS, PLAN_PRO
from app.services.subscription_credits import (
    SUBSCRIPTION_CHANGE_NEW,
    SUBSCRIPTION_CHANGE_RENEWAL,
    SUBSCRIPTION_CHANGE_UPGRADE,
    PaymentPlanChangeError,
    SubscriptionCreditError,
    SubscriptionCreditPolicy,
)

NOW = datetime(2026, 5, 15, 10, 0, tzinfo=UTC)


class FakeSubscriptionRepository:
    def __init__(self, *, current: Subscription | None = None, by_id: dict[int, Subscription] | None = None) -> None:
        self.current = current
        self.by_id = by_id or {}
        self.created: list[Subscription] = []
        self.extended: list[tuple[int, datetime]] = []
        self.closed: list[tuple[int, datetime]] = []

    async def get_effective_paid_subscription(self, _db, *, user_id: int, now=None) -> Subscription | None:
        return self.current

    async def get_by_id(self, _db, *, subscription_id: int) -> Subscription | None:
        return self.by_id.get(subscription_id)

    async def create_active_from_payment(self, _db, *, user_id, plan, payment_id, started_at, expires_at, provider_reference):
        subscription = _subscription(100 + len(self.created), user_id=user_id, plan=plan, payment_id=payment_id)
        subscription.started_at = started_at
        subscription.expires_at = expires_at
        subscription.provider_reference = provider_reference
        self.created.append(subscription)
        return subscription

    async def extend_current_period(self, _db, subscription: Subscription, *, expires_at: datetime) -> Subscription:
        subscription.expires_at = expires_at
        self.extended.append((subscription.id, expires_at))
        return subscription

    async def close_for_upgrade(self, _db, subscription: Subscription, *, ended_at: datetime) -> Subscription:
        subscription.status = "cancelled"
        subscription.expires_at = ended_at
        self.closed.append((subscription.id, ended_at))
        return subscription


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("plan", "duration_days", "expected_expires_at"),
    [
        pytest.param(PLAN_PLUS, 30, datetime(2026, 6, 14, 10, 0, tzinfo=UTC), id="free-to-plus"),
        pytest.param(PLAN_PRO, 90, datetime(2026, 8, 13, 10, 0, tzinfo=UTC), id="free-to-pro"),
    ],
)
async def test_new_paid_plan_starts_active_subscription(plan: str, duration_days: int, expected_expires_at: datetime):
    repo = FakeSubscriptionRepository()
    payment = _payment(plan=plan)

    credit = await SubscriptionCreditPolicy(repo).apply(None, payment=payment, duration_days=duration_days, credited_at=NOW)

    assert credit.change_type == SUBSCRIPTION_CHANGE_NEW
    assert credit.previous_plan == PLAN_FREE
    assert credit.subscription.expires_at == expected_expires_at
    assert payment.audit_metadata["subscription_credit_action"] == SUBSCRIPTION_CHANGE_NEW
    assert repo.created == [credit.subscription]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("plan", "duration_days", "current_expires_at", "expected_expires_at"),
    [
        pytest.param(PLAN_PLUS, 30, datetime(2026, 6, 10, 10, 0, tzinfo=UTC), datetime(2026, 7, 10, 10, 0, tzinfo=UTC), id="plus-renewal"),
        pytest.param(PLAN_PRO, 90, datetime(2026, 8, 1, 10, 0, tzinfo=UTC), datetime(2026, 10, 30, 10, 0, tzinfo=UTC), id="pro-renewal"),
    ],
)
async def test_same_plan_purchase_extends_current_period(
    plan: str,
    duration_days: int,
    current_expires_at: datetime,
    expected_expires_at: datetime,
):
    current = _subscription(10, plan=plan, expires_at=current_expires_at)
    repo = FakeSubscriptionRepository(current=current)
    payment = _payment(plan=plan)

    credit = await SubscriptionCreditPolicy(repo).apply(None, payment=payment, duration_days=duration_days, credited_at=NOW)

    assert credit.change_type == SUBSCRIPTION_CHANGE_RENEWAL
    assert credit.subscription.id == current.id
    assert credit.subscription.expires_at == expected_expires_at
    assert repo.extended == [(current.id, expected_expires_at)]
    assert repo.created == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("current_plan", "requested_plan"),
    [
        pytest.param(PLAN_PLUS, PLAN_PLUS, id="same-plan-preflight"),
        pytest.param(PLAN_PLUS, PLAN_PRO, id="upgrade-preflight"),
    ],
)
async def test_preflight_allows_same_or_higher_plan(current_plan: str, requested_plan: str):
    current = _subscription(11, plan=current_plan)
    repo = FakeSubscriptionRepository(current=current)

    subscription = await SubscriptionCreditPolicy(repo).ensure_plan_change_allowed(
        None,
        user_id=1,
        requested_plan=requested_plan,
        now=NOW,
    )

    assert subscription is current


@pytest.mark.asyncio
async def test_upgrade_closes_lower_plan_and_starts_higher_plan():
    current = _subscription(12, plan=PLAN_PLUS, expires_at=datetime(2026, 6, 10, 10, 0, tzinfo=UTC))
    repo = FakeSubscriptionRepository(current=current)
    payment = _payment(plan=PLAN_PRO)

    credit = await SubscriptionCreditPolicy(repo).apply(None, payment=payment, duration_days=90, credited_at=NOW)

    assert credit.change_type == SUBSCRIPTION_CHANGE_UPGRADE
    assert credit.previous_plan == PLAN_PLUS
    assert current.status == "cancelled"
    assert repo.closed == [(current.id, NOW)]
    assert credit.subscription.plan == PLAN_PRO
    assert credit.subscription.started_at == NOW


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["preflight", "credit"], ids=["downgrade-preflight", "downgrade-credit"])
async def test_downgrade_from_pro_to_plus_is_blocked(method: str):
    repo = FakeSubscriptionRepository(current=_subscription(13, plan=PLAN_PRO))
    policy = SubscriptionCreditPolicy(repo)

    with pytest.raises(PaymentPlanChangeError, match="downgrade_not_allowed"):
        if method == "preflight":
            await policy.ensure_plan_change_allowed(None, user_id=1, requested_plan=PLAN_PLUS, now=NOW)
        else:
            await policy.apply(None, payment=_payment(plan=PLAN_PLUS), duration_days=30, credited_at=NOW)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("metadata", "known_subscription_id", "error"),
    [
        pytest.param({"subscription_id": 21}, 21, None, id="metadata-hit"),
        pytest.param({}, None, SubscriptionCreditError, id="metadata-missing-id"),
        pytest.param({"subscription_id": 99}, None, SubscriptionCreditError, id="metadata-unknown-id"),
    ],
)
async def test_credited_subscription_metadata_lookup(metadata: dict[str, object], known_subscription_id: int | None, error):
    by_id = {known_subscription_id: _subscription(known_subscription_id)} if known_subscription_id is not None else {}
    policy = SubscriptionCreditPolicy(FakeSubscriptionRepository(by_id=by_id))
    payment = _payment(plan=PLAN_PLUS, audit_metadata=metadata)

    if error is not None:
        with pytest.raises(error, match="credited_subscription_missing"):
            await policy.subscription_from_credit_metadata(None, payment)
        return

    assert await policy.subscription_from_credit_metadata(None, payment) is by_id[21]


def _payment(*, plan: str, audit_metadata: dict[str, object] | None = None) -> Payment:
    return Payment(
        id=1,
        user_id=1,
        plan=plan,
        amount_stars=100,
        status="paid",
        idempotency_key=f"pay-{plan}",
        telegram_payment_charge_id=f"tg-{plan}",
        audit_metadata={"kept": "value", **(audit_metadata or {})},
    )


def _subscription(subscription_id: int, *, user_id: int = 1, plan: str = PLAN_PLUS, payment_id: int = 10,
                  expires_at: datetime = datetime(2026, 6, 14, 10, 0, tzinfo=UTC)) -> Subscription:
    return Subscription(
        id=subscription_id,
        user_id=user_id,
        plan=plan,
        status="active",
        started_at=NOW,
        expires_at=expires_at,
        payment_id=payment_id,
    )
