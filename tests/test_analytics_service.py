from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.base import Base
from app.db.models import (
    AnalyticsEvent,
    ApiErrorLog,
    Payment,
    QuizSession,
    Subscription,
    User,
    UserAnswer,
)
from app.repositories.analytics_events import AnalyticsEventRepository
from app.services.analytics import AnalyticsMetricsService, AnalyticsTracker


@pytest_asyncio.fixture
async def db_session() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with session_factory() as session:
        yield session

    await engine.dispose()


@pytest.mark.asyncio
async def test_analytics_repository_rejects_unsafe_metadata(db_session: AsyncSession) -> None:
    repo = AnalyticsEventRepository()

    await repo.record(
        db_session,
        event_name="payment_started",
        user_id=1,
        event_metadata={"raw_payload": {"token": "secret-value"}},
        source="payments",
    )
    await db_session.flush()

    event = await db_session.scalar(select(AnalyticsEvent))
    assert event is not None
    assert event.event_name == "analytics_event_rejected"
    assert event.event_metadata == {
        "rejected_event_name": "payment_started",
        "reason_code": "unsafe_metadata",
    }


@pytest.mark.asyncio
async def test_analytics_repository_rejects_unsafe_metadata_values(db_session: AsyncSession) -> None:
    repo = AnalyticsEventRepository()

    await repo.record(
        db_session,
        event_name="quiz_api_request_failed",
        user_id=1,
        event_metadata={"message": "authorization=Bearer secret-token"},
        source="training",
    )
    await db_session.flush()

    event = await db_session.scalar(select(AnalyticsEvent))
    assert event is not None
    assert event.event_name == "analytics_event_rejected"
    assert event.event_metadata == {
        "rejected_event_name": "quiz_api_request_failed",
        "reason_code": "unsafe_metadata",
    }


@pytest.mark.asyncio
async def test_analytics_tracker_does_not_raise_when_repository_fails() -> None:
    class FailingRepository:
        async def record(self, *args, **kwargs):
            raise RuntimeError("analytics unavailable")

    tracker = AnalyticsTracker(FailingRepository())  # type: ignore[arg-type]

    event = await tracker.record(None, event_name="bot_started", user_id=1)

    assert event is None


@pytest.mark.asyncio
async def test_admin_metrics_cover_daily_funnel_retention_and_operations(db_session: AsyncSession) -> None:
    now = datetime(2026, 5, 15, 12, 0, tzinfo=UTC)
    await _seed_metrics_data(db_session, now)
    service = AnalyticsMetricsService()

    snapshot = await service.get_admin_metrics(db_session, now=now)

    assert snapshot.daily.total_users == 2
    assert snapshot.daily.new_users_today == 1
    assert snapshot.daily.active_users_today == 1
    assert snapshot.daily.training_sessions_today == 1
    assert snapshot.daily.answers_today == 1
    assert snapshot.daily.session_completion_rate_today.rate == 1.0
    assert snapshot.daily.progress_opened_today == 1
    assert snapshot.daily.mistakes_repeated_today == 1
    assert snapshot.daily.active_subscriptions == 1
    assert snapshot.daily.payment_errors_today == 1
    assert snapshot.daily.api_errors_today == 1
    assert snapshot.conversion.paywall_ctr_today.rate == 1.0
    assert snapshot.conversion.payment_success_rate_today.rate == 1.0
    assert snapshot.conversion.free_to_plus_today == 1
    assert snapshot.conversion.subscription_expired_today == 1
    assert snapshot.conversion.expiration_recovery_rate_30d.rate == 1.0
    assert snapshot.retention.day_1.rate == 1.0


async def _seed_metrics_data(db_session: AsyncSession, now: datetime) -> None:
    user_one = User(id=1, telegram_user_id=111, created_at=now - timedelta(days=1))
    user_two = User(id=2, telegram_user_id=222, created_at=now)
    db_session.add_all([user_one, user_two])
    await db_session.flush()

    session = QuizSession(
        id=10,
        user_id=1,
        level="A1",
        theme="Alltag",
        status="completed",
        started_at=now,
        completed_at=now,
        total_questions=1,
        answered_count=1,
        correct_answers=1,
    )
    answer = UserAnswer(
        id=20,
        session_id=10,
        user_id=1,
        external_quiz_id="q1",
        selected_answer="a",
        correct_answer="a",
        is_correct=True,
        answered_at=now,
    )
    db_session.add_all([session, answer])

    events = [
        _event(60, 1, "result_shown", now - timedelta(days=1)),
        _event(61, 1, "training_started", now),
        _event(62, 1, "progress_opened", now),
        _event(63, 1, "mistakes_repeated", now),
        _event(64, 1, "paywall_shown", now),
        _event(65, 1, "paywall_clicked", now),
        _event(66, 1, "payment_started", now),
        _event(67, 1, "payment_succeeded", now),
    ]
    db_session.add_all(events)

    db_session.add_all(
        [
            _credited_payment(30, 1, now),
            _failed_payment(31, 2, now),
            _credited_payment(32, 1, now - timedelta(days=30)),
            Subscription(
                id=40,
                user_id=1,
                plan="plus",
                status="active",
                started_at=now,
                expires_at=now + timedelta(days=30),
                payment_id=30,
            ),
            Subscription(
                id=41,
                user_id=1,
                plan="plus",
                status="expired",
                started_at=now - timedelta(days=30),
                expires_at=now - timedelta(hours=1),
                payment_id=32,
            ),
            ApiErrorLog(
                id=50,
                endpoint="/questions",
                error_category="validation",
                occurred_at=now,
            ),
        ],
    )
    await db_session.flush()


def _credited_payment(payment_id: int, user_id: int, credited_at: datetime) -> Payment:
    return Payment(
        id=payment_id,
        user_id=user_id,
        plan="plus",
        amount_stars=100,
        status="credited",
        idempotency_key=f"pay-{payment_id}",
        telegram_payment_charge_id=f"tg-{payment_id}",
        credited_at=credited_at,
    )


def _failed_payment(payment_id: int, user_id: int, failed_at: datetime) -> Payment:
    return Payment(
        id=payment_id,
        user_id=user_id,
        plan="plus",
        amount_stars=100,
        status="failed",
        idempotency_key=f"pay-{payment_id}",
        failed_at=failed_at,
    )


def _event(event_id: int, user_id: int, event_name: str, event_time: datetime) -> AnalyticsEvent:
    return AnalyticsEvent(
        id=event_id,
        user_id=user_id,
        event_name=event_name,
        event_time=event_time,
        source="test",
    )
