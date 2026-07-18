from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.base import Base
from app.db.models import OutboxEvent, QuizSession, User
from app.repositories.outbox import (
    OUTBOX_DEAD,
    OUTBOX_DONE,
    OUTBOX_FAILED,
    OUTBOX_PENDING,
    OUTBOX_PROCESSING,
    OutboxRepository,
    _retry_delay_seconds,
)
from app.repositories.quiz_sessions import QuizSessionRepository, QuizSessionStatus


@pytest_asyncio.fixture
async def session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    try:
        yield factory
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_quiz_session_repository_creates_tracks_pending_and_finishes_session(session_factory) -> None:
    repo = QuizSessionRepository()
    finished_at = datetime(2026, 7, 16, 12, 0, tzinfo=UTC)

    async with session_factory() as db:
        db.add(User(id=1, telegram_user_id=700001))
        session = await repo.create(
            db,
            user_id=1,
            level="A1",
            theme="T01",
            total_questions=3,
            source="local_quiz_catalog",
            source_metadata={"flow": "mistakes"},
            api_metadata={"catalog_id": "cat"},
        )
        session.id = 10
        await db.flush()

        assert session.status == QuizSessionStatus.active
        assert session.session_type == "mistakes"
        assert await repo.get_active_for_user(db, 1) is session
        assert await repo.get_by_id_for_user(db, session.id, 1) is session

        await repo.set_pending_question(db, session, {"question_token": "tok"})
        assert session.api_metadata == {"catalog_id": "cat", "pending_question": {"question_token": "tok"}}
        await repo.clear_pending_question(db, session)
        assert session.api_metadata == {"catalog_id": "cat"}
        assert await repo.increment_shown_questions_count(db, session, 2) == 2
        assert await repo.increment_answered_count(db, session, 1) == 1
        assert await repo.increment_correct_answers(db, session, 1) == 1

        await repo.mark_completed(db, session, finished_at=finished_at)

        assert session.status == QuizSessionStatus.completed
        assert session.finished_at == finished_at
        assert session.completed_at == finished_at
        assert session.abandoned_at is None
        assert session.failed_at is None


@pytest.mark.asyncio
async def test_quiz_session_repository_marks_cancelled_and_failed_with_distinct_timestamps(session_factory) -> None:
    repo = QuizSessionRepository()
    cancelled_at = datetime(2026, 7, 16, 13, 0, tzinfo=UTC)
    failed_at = datetime(2026, 7, 16, 14, 0, tzinfo=UTC)

    async with session_factory() as db:
        db.add(User(id=1, telegram_user_id=700001))
        cancelled = await repo.create(
            db,
            user_id=1,
            level="A1",
            theme=None,
            total_questions=1,
            source="local_quiz_catalog",
        )
        cancelled.id = 10
        failed = await repo.create(
            db,
            user_id=1,
            level="B1",
            theme="T02",
            total_questions=1,
            source="local_quiz_catalog",
        )
        failed.id = 11

        await repo.mark_cancelled(db, cancelled, finished_at=cancelled_at)
        await repo.mark_failed(db, failed, finished_at=failed_at)

        assert cancelled.status == QuizSessionStatus.cancelled
        assert cancelled.abandoned_at == cancelled_at
        assert cancelled.completed_at is None
        assert failed.status == QuizSessionStatus.failed
        assert failed.failed_at == failed_at
        assert failed.completed_at is None


@pytest.mark.asyncio
async def test_outbox_repository_enqueue_is_idempotent_and_claims_due_events_in_order(session_factory) -> None:
    repo = OutboxRepository()
    now = datetime(2026, 7, 16, 12, 0, tzinfo=UTC)

    async with session_factory() as db:
        first = await repo.enqueue(
            db,
            event_type="answer.accepted",
            aggregate_type="user_answer",
            aggregate_id=1,
            idempotency_key="answer:1",
            payload={"answer_id": 1},
        )
        first.status = OUTBOX_PENDING
        first.next_attempt_at = now
        first.created_at = now
        duplicate = await repo.enqueue(
            db,
            event_type="answer.accepted",
            aggregate_type="user_answer",
            aggregate_id=1,
            idempotency_key="answer:1",
            payload={"answer_id": 1},
        )
        delayed = OutboxEvent(
            id=99,
            event_type="answer.accepted",
            aggregate_type="user_answer",
            aggregate_id=99,
            idempotency_key="answer:delayed",
            payload={"answer_id": 99},
            next_attempt_at=now + timedelta(minutes=5),
        )
        db.add(delayed)
        await db.flush()

        claimed = await repo.claim_batch(db, worker_id="worker-1", batch_size=10, now=now)

        assert duplicate is first
        assert [event.id for event in claimed] == [first.id]
        assert claimed[0].status == OUTBOX_PROCESSING
        assert claimed[0].locked_by == "worker-1"
        assert delayed.status == OUTBOX_PENDING


@pytest.mark.asyncio
async def test_outbox_repository_failure_backoff_dead_letter_and_done_reset_fields(session_factory) -> None:
    repo = OutboxRepository()
    now = datetime(2026, 7, 16, 12, 0, tzinfo=UTC)

    async with session_factory() as db:
        retryable = await repo.enqueue(
            db,
            event_type="answer.accepted",
            aggregate_type="user_answer",
            aggregate_id=1,
            idempotency_key="answer:retry",
            payload={},
        )
        retryable.status = OUTBOX_PROCESSING
        retryable.locked_at = now
        retryable.locked_by = "worker-1"

        await repo.mark_failed(db, retryable, error_message="x" * 1200, now=now)

        assert retryable.status == OUTBOX_FAILED
        assert retryable.retry_count == 1
        assert retryable.last_error == "x" * 1000
        assert retryable.locked_at is None
        assert retryable.next_attempt_at == now + timedelta(seconds=1)

        retryable.retry_count = retryable.max_retries - 1
        await repo.mark_failed(db, retryable, error_message="permanent", now=now)

        assert retryable.status == OUTBOX_DEAD
        assert retryable.dead_at == now
        assert retryable.failed_at == now

        await repo.mark_done(db, retryable, now=now + timedelta(seconds=1))

        assert retryable.status == OUTBOX_DONE
        assert retryable.processed_at == now + timedelta(seconds=1)
        assert retryable.failed_at is None
        assert retryable.dead_at is None
        assert retryable.last_error is None


@pytest.mark.asyncio
async def test_outbox_repository_requeues_stale_processing_and_reports_pending_lag(session_factory) -> None:
    repo = OutboxRepository()
    now = datetime(2026, 7, 16, 12, 0, tzinfo=UTC)

    async with session_factory() as db:
        stale = OutboxEvent(
            id=1,
            event_type="answer.accepted",
            aggregate_type="user_answer",
            aggregate_id=1,
            idempotency_key="stale",
            payload={},
            status=OUTBOX_PROCESSING,
            locked_at=now - timedelta(minutes=10),
            locked_by="worker-1",
            created_at=now - timedelta(seconds=30),
        )
        fresh = OutboxEvent(
            id=2,
            event_type="answer.accepted",
            aggregate_type="user_answer",
            aggregate_id=2,
            idempotency_key="fresh",
            payload={},
            status=OUTBOX_PROCESSING,
            locked_at=now,
            locked_by="worker-2",
            created_at=now,
        )
        db.add_all([stale, fresh])
        await db.flush()

        requeued = await repo.requeue_stale_processing(db, stale_after_seconds=60, now=now)
        lag = await repo.pending_lag_seconds(db, now=now)

        assert requeued == 1
        assert stale.status == OUTBOX_FAILED
        assert stale.locked_by is None
        assert stale.next_attempt_at == now
        assert fresh.status == OUTBOX_PROCESSING
        assert lag == 30.0


@pytest.mark.asyncio
async def test_outbox_repository_id_based_updates_are_noops_for_missing_rows(session_factory) -> None:
    repo = OutboxRepository()

    async with session_factory() as db:
        await repo.mark_done_many_by_id(db, [])
        await repo.mark_done_by_id(db, 404)
        await repo.mark_failed_by_id(db, 404, error_message="missing")

        assert list((await db.scalars(select(OutboxEvent))).all()) == []


def test_outbox_retry_delay_is_exponential_and_capped() -> None:
    assert _retry_delay_seconds(0) == 1
    assert _retry_delay_seconds(1) == 1
    assert _retry_delay_seconds(3) == 4
    assert _retry_delay_seconds(20) == 300
