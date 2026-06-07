from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from app.config import Settings
from app.db.models import Subscription
from app.services import entitlements as entitlements_module
from app.services import subscription_credits
from app.services.entitlements import (
    DailyLimitExceededError,
    EntitlementDeniedError,
    EntitlementService,
    FEATURE_FULL_PROGRESS_MAP,
    PLAN_FREE,
    PLAN_PLUS,
)

NOW = datetime(2026, 5, 15, 10, 0, tzinfo=UTC)


@pytest.mark.asyncio
async def test_ensure_entitlement_denial_flushes_new_user() -> None:
    user = SimpleNamespace(id=None)
    db = FakeDb(user=user)
    service = _service(user=user)

    with pytest.raises(EntitlementDeniedError) as error:
        await service.ensure_entitlement(db, 111, feature=FEATURE_FULL_PROGRESS_MAP, now=NOW)

    assert db.flushed == 1
    assert error.value.decision.reason_code == "entitlement_required"


@pytest.mark.asyncio
async def test_subscription_status_flushes_new_user_without_latest_subscription() -> None:
    user = SimpleNamespace(id=None)
    db = FakeDb(user=user)

    state = await _service(user=user).get_subscription_status_state(db, 111, now=NOW)

    assert db.flushed == 1
    assert state.access_plan == PLAN_FREE
    assert state.status == "inactive"


@pytest.mark.asyncio
async def test_charge_daily_question_rejects_when_remaining_is_zero() -> None:
    service = _service(user=SimpleNamespace(id=77), daily_limit_repo=FakeDailyLimitRepo())

    with pytest.raises(DailyLimitExceededError) as error:
        await service.charge_daily_question(None, 111, now=NOW)

    assert error.value.state.remaining == 0


@pytest.mark.asyncio
async def test_record_subscription_expired_handles_none_failed_and_duplicate_paths(monkeypatch) -> None:
    service = _service(user=SimpleNamespace(id=77))
    await service._record_subscription_expired(None, _subscription(expires_at=None))

    async def raises(*args, **kwargs) -> bool:
        raise RuntimeError("analytics unavailable")

    monkeypatch.setattr(entitlements_module, "has_user_event_since", raises)
    await service._record_subscription_expired(None, _subscription())

    async def already_recorded(*args, **kwargs) -> bool:
        return True

    monkeypatch.setattr(entitlements_module, "has_user_event_since", already_recorded)
    await service._record_subscription_expired(None, _subscription())


def test_subscription_status_helper_covers_pending_inactive_and_none_time() -> None:
    assert entitlements_module._subscription_status(_subscription(), NOW) == "pending"
    assert entitlements_module._subscription_status(_subscription(status="paused"), NOW) == "inactive"
    assert entitlements_module._as_aware_utc(None) is None


def test_subscription_credit_datetime_helper_accepts_naive_time() -> None:
    assert subscription_credits._as_aware_utc(datetime(2026, 5, 15, 10, 0)) == NOW


class FakeDb:
    def __init__(self, *, user) -> None:
        self.user = user
        self.flushed = 0

    async def flush(self) -> None:
        self.flushed += 1
        if self.user.id is None:
            self.user.id = 77


class FakeUserRepo:
    def __init__(self, user) -> None:
        self.user = user

    async def create_if_missing(self, db, telegram_user_id: int):
        return self.user


class FakeSubscriptionRepo:
    async def get_effective_paid_subscription(self, db, *, user_id: int, now=None):
        return None

    async def get_latest_for_user(self, db, *, user_id: int):
        return None


class FakeDailyLimitRepo:
    async def get_or_create_for_today(self, db, **kwargs):
        return SimpleNamespace(user_id=77, question_limit=1, questions_used=1, reset_at=NOW)


class FakeAnalyticsRepo:
    async def record(self, db, **kwargs):
        return SimpleNamespace(**kwargs)


def _service(*, user, daily_limit_repo=None) -> EntitlementService:
    return EntitlementService(
        user_repo=FakeUserRepo(user),
        subscription_repo=FakeSubscriptionRepo(),
        daily_limit_repo=daily_limit_repo,
        analytics_repo=FakeAnalyticsRepo(),
        settings=_settings(),
    )


def _subscription(
    *,
    status: str = "active",
    expires_at: datetime | None = datetime(2026, 6, 14, 10, 0, tzinfo=UTC),
) -> Subscription:
    return Subscription(
        id=1,
        user_id=77,
        plan=PLAN_PLUS,
        status=status,
        started_at=NOW,
        expires_at=expires_at,
        payment_id=1,
    )


def _settings() -> Settings:
    return Settings(
        FREE_DAILY_QUESTION_LIMIT=1,
        PLUS_DAILY_QUESTION_LIMIT=3,
        PRO_DAILY_QUESTION_LIMIT=5,
    )
