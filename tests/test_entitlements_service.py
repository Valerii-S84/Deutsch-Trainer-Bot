from __future__ import annotations

from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import Settings
from app.db.base import Base
from app.db.models import AnalyticsEvent, DailyLimit, Payment, Subscription, User
from app.services.entitlements import (
    DailyLimitExceededError,
    EntitlementService,
    FEATURE_ADVANCED_STATISTICS,
    FEATURE_FULL_PROGRESS_MAP,
    FEATURE_MISTAKE_REPEAT,
    FEATURE_SELECT_LEVEL,
    PLAN_FREE,
    PLAN_PLUS,
    PLAN_PRO,
)


@pytest_asyncio.fixture
async def db_session() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)

    async with engine.begin() as connection:
        await connection.run_sync(
            Base.metadata.create_all,
            tables=[
                User.__table__,
                Payment.__table__,
                Subscription.__table__,
                DailyLimit.__table__,
                AnalyticsEvent.__table__,
            ],
        )

    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with session_factory() as session:
        yield session

    await engine.dispose()


def _settings() -> Settings:
    return Settings(
        FREE_DAILY_QUESTION_LIMIT=1,
        PLUS_DAILY_QUESTION_LIMIT=3,
        PRO_DAILY_QUESTION_LIMIT=5,
    )


async def _user(db_session: AsyncSession, *, user_id: int, telegram_user_id: int) -> User:
    user = User(id=user_id, telegram_user_id=telegram_user_id)
    db_session.add(user)
    await db_session.flush()
    return user


async def _credited_subscription(
    db_session: AsyncSession,
    *,
    user: User,
    plan: str,
    expires_at: datetime,
    payment_status: str = "credited",
    credited: bool = True,
    subscription_status: str = "active",
) -> Subscription:
    payment = Payment(
        id=user.id,
        user_id=user.id,
        plan=plan,
        amount_stars=100,
        status=payment_status,
        idempotency_key=f"pay-{user.id}-{plan}",
        credited_at=datetime(2026, 5, 14, 10, 0, tzinfo=UTC) if credited else None,
    )
    subscription = Subscription(
        id=user.id,
        user_id=user.id,
        plan=plan,
        status=subscription_status,
        started_at=datetime(2026, 5, 14, 10, 0, tzinfo=UTC),
        expires_at=expires_at,
        payment_id=payment.id,
    )
    db_session.add_all([payment, subscription])
    await db_session.flush()
    return subscription


@pytest.mark.asyncio
async def test_free_plan_has_free_features_only(db_session: AsyncSession) -> None:
    service = EntitlementService(settings=_settings())

    free = await service.check_entitlement(db_session, 111, feature=FEATURE_SELECT_LEVEL)
    paid = await service.check_entitlement(db_session, 111, feature=FEATURE_FULL_PROGRESS_MAP)

    assert free.allowed is True
    assert free.user_plan == PLAN_FREE
    assert paid.allowed is False
    assert paid.required_plan == PLAN_PLUS


@pytest.mark.asyncio
async def test_active_credited_plus_unlocks_plus_features(db_session: AsyncSession) -> None:
    user = await _user(db_session, user_id=1, telegram_user_id=112)
    await _credited_subscription(
        db_session,
        user=user,
        plan=PLAN_PLUS,
        expires_at=datetime(2026, 5, 20, 10, 0, tzinfo=UTC),
    )
    service = EntitlementService(settings=_settings())

    plus = await service.check_entitlement(
        db_session,
        user.telegram_user_id,
        feature=FEATURE_MISTAKE_REPEAT,
        now=datetime(2026, 5, 15, 10, 0, tzinfo=UTC),
    )
    pro = await service.check_entitlement(
        db_session,
        user.telegram_user_id,
        feature=FEATURE_ADVANCED_STATISTICS,
        now=datetime(2026, 5, 15, 10, 0, tzinfo=UTC),
    )

    assert plus.allowed is True
    assert plus.user_plan == PLAN_PLUS
    assert pro.allowed is False


@pytest.mark.asyncio
async def test_pro_includes_plus_features(db_session: AsyncSession) -> None:
    user = await _user(db_session, user_id=2, telegram_user_id=113)
    await _credited_subscription(
        db_session,
        user=user,
        plan=PLAN_PRO,
        expires_at=datetime(2026, 5, 20, 10, 0, tzinfo=UTC),
    )
    service = EntitlementService(settings=_settings())

    decision = await service.check_entitlement(
        db_session,
        user.telegram_user_id,
        feature=FEATURE_MISTAKE_REPEAT,
        now=datetime(2026, 5, 15, 10, 0, tzinfo=UTC),
    )

    assert decision.allowed is True
    assert decision.user_plan == PLAN_PRO


@pytest.mark.asyncio
async def test_pending_or_uncredited_subscription_does_not_unlock(db_session: AsyncSession) -> None:
    user = await _user(db_session, user_id=3, telegram_user_id=114)
    await _credited_subscription(
        db_session,
        user=user,
        plan=PLAN_PLUS,
        expires_at=datetime(2026, 5, 20, 10, 0, tzinfo=UTC),
        credited=False,
        subscription_status="pending",
    )
    active_uncredited_user = await _user(db_session, user_id=33, telegram_user_id=334)
    await _credited_subscription(
        db_session,
        user=active_uncredited_user,
        plan=PLAN_PLUS,
        expires_at=datetime(2026, 5, 20, 10, 0, tzinfo=UTC),
        credited=False,
        subscription_status="active",
    )
    service = EntitlementService(settings=_settings())

    decision = await service.check_entitlement(
        db_session,
        user.telegram_user_id,
        feature=FEATURE_FULL_PROGRESS_MAP,
        now=datetime(2026, 5, 15, 10, 0, tzinfo=UTC),
    )

    assert decision.allowed is False
    assert decision.user_plan == PLAN_FREE
    active_uncredited_decision = await service.check_entitlement(
        db_session,
        active_uncredited_user.telegram_user_id,
        feature=FEATURE_FULL_PROGRESS_MAP,
        now=datetime(2026, 5, 15, 10, 0, tzinfo=UTC),
    )
    assert active_uncredited_decision.allowed is False
    assert active_uncredited_decision.user_plan == PLAN_FREE


@pytest.mark.asyncio
async def test_subscription_status_reports_active_credited_paid_access(db_session: AsyncSession) -> None:
    user = await _user(db_session, user_id=36, telegram_user_id=361)
    await _credited_subscription(
        db_session,
        user=user,
        plan=PLAN_PLUS,
        expires_at=datetime(2026, 5, 20, 10, 0, tzinfo=UTC),
    )
    service = EntitlementService(settings=_settings())

    status_state = await service.get_subscription_status_state(
        db_session,
        user.telegram_user_id,
        now=datetime(2026, 5, 15, 10, 0, tzinfo=UTC),
    )

    assert status_state.access_plan == PLAN_PLUS
    assert status_state.status_plan == PLAN_PLUS
    assert status_state.status == "active"
    assert status_state.subscription is not None


@pytest.mark.asyncio
async def test_subscription_status_preserves_pending_plan_without_paid_access(db_session: AsyncSession) -> None:
    user = await _user(db_session, user_id=34, telegram_user_id=341)
    await _credited_subscription(
        db_session,
        user=user,
        plan=PLAN_PRO,
        expires_at=datetime(2026, 5, 20, 10, 0, tzinfo=UTC),
        credited=False,
        subscription_status="pending",
    )
    service = EntitlementService(settings=_settings())

    status_state = await service.get_subscription_status_state(
        db_session,
        user.telegram_user_id,
        now=datetime(2026, 5, 15, 10, 0, tzinfo=UTC),
    )

    assert status_state.access_plan == PLAN_FREE
    assert status_state.status_plan == PLAN_PRO
    assert status_state.status == "pending"
    assert status_state.subscription is not None


@pytest.mark.asyncio
async def test_subscription_status_treats_time_expired_subscription_as_expired(db_session: AsyncSession) -> None:
    user = await _user(db_session, user_id=35, telegram_user_id=351)
    await _credited_subscription(
        db_session,
        user=user,
        plan=PLAN_PLUS,
        expires_at=datetime(2026, 5, 14, 10, 0, tzinfo=UTC),
    )
    service = EntitlementService(settings=_settings())

    status_state = await service.get_subscription_status_state(
        db_session,
        user.telegram_user_id,
        now=datetime(2026, 5, 15, 10, 0, tzinfo=UTC),
    )

    assert status_state.access_plan == PLAN_FREE
    assert status_state.status_plan == PLAN_PLUS
    assert status_state.status == "expired"
    assert status_state.expires_at == datetime(2026, 5, 14, 10, 0, tzinfo=UTC)


@pytest.mark.asyncio
async def test_expired_subscription_returns_to_free_without_deleting_data(db_session: AsyncSession) -> None:
    user = await _user(db_session, user_id=4, telegram_user_id=115)
    subscription = await _credited_subscription(
        db_session,
        user=user,
        plan=PLAN_PLUS,
        expires_at=datetime(2026, 5, 14, 10, 0, tzinfo=UTC),
    )
    service = EntitlementService(settings=_settings())

    decision = await service.check_entitlement(
        db_session,
        user.telegram_user_id,
        feature=FEATURE_FULL_PROGRESS_MAP,
        now=datetime(2026, 5, 15, 10, 0, tzinfo=UTC),
    )

    assert decision.allowed is False
    assert decision.user_plan == PLAN_FREE
    rows = await db_session.execute(select(Subscription).where(Subscription.user_id == user.id))
    assert subscription in list(rows.scalars().all())


@pytest.mark.asyncio
async def test_daily_limit_hit_records_analytics(db_session: AsyncSession) -> None:
    service = EntitlementService(settings=_settings())

    await service.ensure_daily_question_available(db_session, 116, now=datetime(2026, 5, 14, 10, 0, tzinfo=UTC))
    await service.charge_daily_question(db_session, 116, now=datetime(2026, 5, 14, 10, 0, tzinfo=UTC))

    with pytest.raises(DailyLimitExceededError):
        await service.ensure_daily_question_available(
            db_session,
            116,
            session_id=12,
            level="A1",
            theme="Alltag",
            now=datetime(2026, 5, 14, 11, 0, tzinfo=UTC),
        )

    rows = await db_session.execute(select(AnalyticsEvent.event_name).order_by(AnalyticsEvent.id.asc()))
    event_names = [event_name for event_name, in rows.all()]
    assert event_names == ["daily_limit_hit", "training_blocked_by_limit", "paywall_shown"]


@pytest.mark.asyncio
async def test_lowered_daily_limit_config_does_not_violate_existing_usage(db_session: AsyncSession) -> None:
    high_limit_service = EntitlementService(
        settings=Settings(
            FREE_DAILY_QUESTION_LIMIT=5,
            PLUS_DAILY_QUESTION_LIMIT=10,
            PRO_DAILY_QUESTION_LIMIT=20,
        ),
    )
    lowered_limit_service = EntitlementService(
        settings=Settings(
            FREE_DAILY_QUESTION_LIMIT=1,
            PLUS_DAILY_QUESTION_LIMIT=10,
            PRO_DAILY_QUESTION_LIMIT=20,
        ),
    )

    await high_limit_service.charge_daily_question(db_session, 117, now=datetime(2026, 5, 14, 10, 0, tzinfo=UTC))
    await high_limit_service.charge_daily_question(db_session, 117, now=datetime(2026, 5, 14, 11, 0, tzinfo=UTC))

    with pytest.raises(DailyLimitExceededError) as exc_info:
        await lowered_limit_service.ensure_daily_question_available(
            db_session,
            117,
            now=datetime(2026, 5, 14, 12, 0, tzinfo=UTC),
        )

    assert exc_info.value.state.question_limit == 2
    assert exc_info.value.state.remaining == 0
    await db_session.flush()
