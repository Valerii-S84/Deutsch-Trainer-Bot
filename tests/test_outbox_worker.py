from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import pytest
import pytest_asyncio

from app.db.base import Base
from app.db.models import AnalyticsEvent, Mistake, OutboxEvent, Progress, QuizSession, User, UserAnswer
from app.repositories.outbox import OUTBOX_DONE, OutboxRepository
from app.workers.outbox import ANSWER_ACCEPTED_EVENT, OutboxWorker


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
        "question_token": "token-1",
        "item_id": "q1",
        "level": "A1",
        "theme": "Alltag",
        "theme_key": "alltag",
        "selected_answer": "a1",
        "correct_answer": "a2",
        "is_correct": False,
        "session_type": "regular",
        "position": 1,
        "available_items_count": 10,
        "metadata_snapshot": {"catalog_id": "cat"},
        "session_completed": False,
        "answered_count": 1,
        "correct_answers": 0,
        "total_questions": 5,
    }
