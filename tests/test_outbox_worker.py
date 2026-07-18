from __future__ import annotations

import asyncio
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import pytest
import pytest_asyncio

from app.db.base import Base
from app.db.models import AnalyticsEvent, Mistake, OutboxEvent, Progress, QuizSession, User, UserAnswer
from app.repositories.outbox import OUTBOX_DONE, OutboxRepository
from app.workers.outbox import ANSWER_ACCEPTED_EVENT, OutboxWorker
from app.workers.outbox_payloads import parse_answer_accepted_payload


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
async def test_outbox_worker_processes_answer_accepted_side_effects_once(session_factory) -> None:
    async with session_factory() as db:
        payload = await _seed_answer_event(db)
        await db.commit()

    worker = OutboxWorker(session_factory=session_factory, batch_size=10)
    assert await worker.process_once() == 1
    assert await worker.process_once() == 0

    async with session_factory() as db:
        event = await db.scalar(select(OutboxEvent).where(OutboxEvent.idempotency_key == "answer.accepted:1"))
        progress = await db.scalar(select(Progress).where(Progress.user_id == payload["user_id"]))
        mistake = await db.scalar(select(Mistake).where(Mistake.user_id == payload["user_id"]))
        analytics = list((await db.scalars(select(AnalyticsEvent))).all())

    assert event is not None
    assert event.status == OUTBOX_DONE
    assert progress is not None
    assert progress.total_answered == 1
    assert progress.total_correct == 0
    assert mistake is not None
    assert mistake.external_quiz_id == "q1"
    assert [item.event_name for item in analytics] == ["question_answered"]


@pytest.mark.asyncio
async def test_outbox_worker_prefers_batch_path_when_available(session_factory) -> None:
    worker = OutboxWorker(session_factory=session_factory)
    batch_event = SimpleNamespace(id=1)
    worker._claim_events = AsyncMock(return_value=[batch_event])  # type: ignore[method-assign]
    worker._try_process_batch = AsyncMock(return_value=True)  # type: ignore[method-assign]
    worker._process_event = AsyncMock()  # type: ignore[method-assign]

    processed = await worker.process_once()

    assert processed == 1
    worker._try_process_batch.assert_awaited_once_with([batch_event])
    worker._process_event.assert_not_called()


@pytest.mark.asyncio
async def test_outbox_worker_run_forever_retries_loop_error(monkeypatch, session_factory) -> None:
    worker = OutboxWorker(session_factory=session_factory)
    calls = 0
    sleeps: list[float] = []

    async def process_once() -> int:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("db unavailable")
        raise asyncio.CancelledError

    async def sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr(worker, "process_once", process_once)
    monkeypatch.setattr("app.workers.outbox.asyncio.sleep", sleep)

    with pytest.raises(asyncio.CancelledError):
        await worker.run_forever(idle_sleep_seconds=0.01)

    assert calls == 2
    assert sleeps == [1.0]


def test_parse_answer_payload_reads_v2_metadata_fields() -> None:
    payload = parse_answer_accepted_payload(_answer_payload())

    assert payload.session_item_id == 11
    assert payload.catalog_id == "cat"
    assert payload.item_version == "1.0"
    assert payload.theme_id == "T01"
    assert payload.answered_at == datetime.fromisoformat("2026-07-01T10:00:00+00:00")


async def _seed_answer_event(db: AsyncSession) -> dict[str, object]:
    user = User(id=1, telegram_user_id=700001)
    session = QuizSession(
        id=1,
        user_id=1,
        level="A1",
        theme="Alltag",
        status="active",
        total_questions=5,
        answered_count=1,
        correct_answers=0,
        source="local_quiz_catalog",
    )
    answer = UserAnswer(
        id=1,
        session_id=1,
        user_id=1,
        external_quiz_id="q1",
        item_id="q1",
        level="A1",
        theme="Alltag",
        selected_answer="a1",
        correct_answer="a2",
        is_correct=False,
        session_type="regular",
    )
    db.add_all([user, session, answer])
    payload = _answer_payload()
    await OutboxRepository().enqueue(
        db,
        event_type=ANSWER_ACCEPTED_EVENT,
        aggregate_type="user_answer",
        aggregate_id=1,
        idempotency_key="answer.accepted:1",
        payload=payload,
    )
    return payload


def _answer_payload() -> dict[str, object]:
    return {
        "answer_id": 1,
        "telegram_user_id": 700001,
        "user_id": 1,
        "session_id": 1,
        "session_item_id": 11,
        "question_token": "token-1",
        "catalog_id": "cat",
        "item_id": "q1",
        "item_version": "1.0",
        "level": "A1",
        "theme": "Alltag",
        "theme_id": "T01",
        "theme_key": "alltag",
        "selected_answer": "a1",
        "correct_answer": "a2",
        "is_correct": False,
        "session_type": "regular",
        "answered_at": "2026-07-01T10:00:00+00:00",
        "position": 1,
        "available_items_count": 10,
        "metadata_snapshot": {"catalog_id": "cat"},
        "session_completed": False,
        "answered_count": 1,
        "correct_answers": 0,
        "total_questions": 5,
    }
