from __future__ import annotations

from dataclasses import asdict, replace

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.base import Base
from app.db.models import OutboxEvent, QuestionReference, QuizSession, TrainingSessionItem, User, UserAnswer
from app.runtime.answer_persistence_queue import AnswerPersistEnqueueResult, AnswerPersistenceMessage
from app.services.training_answer_write_behind import accept_answer_write_behind
from app.services.training_answer_write_behind import accept_answer_write_behind_many, AnswerWriteBehindRequest
from app.services.training_payloads import AnswerResult, QuizQuestionPayload
from app.workers.answer_persistence import (
    AnswerPersistenceWorker,
    PersistableAnswerEvent,
    persist_answer_events,
)


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
async def test_write_behind_answer_uses_cached_state_and_enqueues_event(monkeypatch) -> None:
    pending = _pending_payload()

    async def cached_pending_question(**_kwargs):
        return pending

    fake_queue = _AcceptingQueue()
    monkeypatch.setattr(
        "app.services.training_answer_write_behind.get_cached_pending_question_if_enabled",
        cached_pending_question,
    )

    result = await accept_answer_write_behind(
        queue=fake_queue,
        telegram_user_id=700001,
        session_id=1,
        question_token="tok1",
        selected_option_id="a1",
        telegram_update_id=9001,
        callback_query_id="cbq-9001",
    )

    assert result.is_correct is False
    assert result.is_duplicate is False
    assert result.correct_answer_text == "Antwort B"
    assert fake_queue.calls[0]["answer_event_id"] == "update:9001"
    event_payload = fake_queue.calls[0]["event_payload"]
    assert event_payload["user_id"] == 1
    assert event_payload["telegram_update_id"] == 9001
    assert event_payload["session_item_id"] == 11


@pytest.mark.asyncio
async def test_write_behind_duplicate_returns_duplicate_result(monkeypatch) -> None:
    pending = _pending_payload()

    async def cached_pending_question(**_kwargs):
        return pending

    duplicate_payload = asdict(_expected_result())
    fake_queue = _DuplicateQueue(duplicate_payload)
    monkeypatch.setattr(
        "app.services.training_answer_write_behind.get_cached_pending_question_if_enabled",
        cached_pending_question,
    )

    result = await accept_answer_write_behind(
        queue=fake_queue,
        telegram_user_id=700001,
        session_id=1,
        question_token="tok1",
        selected_option_id="a1",
        telegram_update_id=9001,
        callback_query_id="cbq-9001",
    )

    assert result.is_duplicate is True
    assert result.session_id == 1


@pytest.mark.asyncio
async def test_write_behind_many_batches_cached_state_and_enqueue(monkeypatch) -> None:
    pending = _pending_payload()
    second_pending = replace(
        pending,
        session_id=2,
        question_token="tok2",
        training_session_item_id=12,
    )

    async def cached_pending_questions(_keys):
        return [pending, second_pending]

    fake_queue = _BatchAcceptingQueue()
    monkeypatch.setattr(
        "app.services.training_answer_write_behind.get_cached_pending_questions_if_enabled",
        cached_pending_questions,
    )

    results = await accept_answer_write_behind_many(
        queue=fake_queue,
        requests=[
            AnswerWriteBehindRequest(700001, 1, "tok1", "a1", 9001, "cbq-9001"),
            AnswerWriteBehindRequest(700001, 2, "tok2", "a2", 9002, "cbq-9002"),
        ],
    )

    assert [result.is_correct for result in results if not isinstance(result, Exception)] == [False, True]
    assert [item.answer_event_id for item in fake_queue.items] == ["update:9001", "update:9002"]
    assert [item.question_dedupe_id for item in fake_queue.items] == ["1:tok1", "2:tok2"]


@pytest.mark.asyncio
async def test_persist_answer_events_batches_and_is_idempotent(session_factory) -> None:
    async with session_factory() as db:
        db.add_all(_persistence_seed_rows())
        await db.commit()

    event = _persistable_event()
    async with session_factory() as db:
        async with db.begin():
            await persist_answer_events(db, [event])
        async with db.begin():
            await persist_answer_events(db, [event])

    async with session_factory() as db:
        answers = list((await db.scalars(select(UserAnswer))).all())
        outbox_events = list((await db.scalars(select(OutboxEvent))).all())
        session = await db.get(QuizSession, 1)
        item = await db.get(TrainingSessionItem, 11)

    _assert_persisted_answer_state(answers, outbox_events, session, item)


def _persistence_seed_rows() -> list[object]:
    return [
        User(id=1, telegram_user_id=700001),
        QuizSession(
            id=1,
            user_id=1,
            level="A1",
            theme="Alltag",
            status="active",
            total_questions=5,
            answered_count=0,
            correct_answers=0,
            source="local_quiz_catalog",
        ),
        QuestionReference(
            id=1,
            catalog_id="cat",
            item_id="q1",
            item_version="1.0",
            level="A1",
            theme="Alltag",
            source="local_quiz_catalog",
            metadata_snapshot={"catalog_id": "cat"},
            question_text_snapshot="Was ist korrekt?",
            correct_answer_snapshot="Antwort B",
        ),
        TrainingSessionItem(
            id=11,
            session_id=1,
            user_id=1,
            question_reference_id=1,
            item_id="q1",
            position=1,
            status="shown",
        ),
    ]


def _assert_persisted_answer_state(
    answers: list[UserAnswer],
    outbox_events: list[OutboxEvent],
    session: QuizSession | None,
    item: TrainingSessionItem | None,
) -> None:
    assert len(answers) == 1
    assert answers[0].telegram_update_id == 9001
    assert len(outbox_events) == 1
    assert outbox_events[0].payload["answer_id"] == answers[0].id
    assert session is not None
    assert session.answered_count == 1
    assert item is not None
    assert item.status == "answered"


@pytest.mark.asyncio
async def test_answer_persistence_worker_retries_failed_batch(monkeypatch) -> None:
    queue = _RetryQueue()
    worker = AnswerPersistenceWorker(queue=queue, batch_size=1, max_attempts=2)

    async def fail_persist(_messages):
        raise RuntimeError("db down")

    monkeypatch.setattr(worker, "_persist_messages", fail_persist)

    processed = await worker.process_once()

    assert processed == 0
    assert queue.retried == ["1-0"]


class _AcceptingQueue:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def enqueue_answer_event(self, **kwargs):
        self.calls.append(kwargs)
        return AnswerPersistEnqueueResult(
            accepted=True,
            duplicate=False,
            duplicate_reason=None,
            answer_event_id=str(kwargs["answer_event_id"]),
            result_payload=kwargs["result_payload"],
            stream_id="1-0",
        )


class _DuplicateQueue:
    def __init__(self, result_payload: dict[str, object]) -> None:
        self._result_payload = result_payload

    async def enqueue_answer_event(self, **kwargs):
        return AnswerPersistEnqueueResult(
            accepted=False,
            duplicate=True,
            duplicate_reason="duplicate_event",
            answer_event_id=str(kwargs["answer_event_id"]),
            result_payload=self._result_payload,
            stream_id=None,
        )


class _BatchAcceptingQueue:
    def __init__(self) -> None:
        self.items = []

    async def enqueue_answer_events(self, items):
        self.items = list(items)
        return [
            AnswerPersistEnqueueResult(
                accepted=True,
                duplicate=False,
                duplicate_reason=None,
                answer_event_id=item.answer_event_id,
                result_payload=item.result_payload,
                stream_id=f"{index}-0",
            )
            for index, item in enumerate(items, start=1)
        ]


class _RetryQueue:
    def __init__(self) -> None:
        self.message = AnswerPersistenceMessage(
            message_id="1-0",
            answer_event_id="update:9001",
            payload={},
            enqueued_at_ms=1,
            attempt=0,
        )
        self.retried: list[str] = []

    async def claim_stale(self, **_kwargs):
        return []

    async def read_batch(self, **_kwargs):
        return [self.message]

    async def retry_or_dead(self, message, **_kwargs):
        self.retried.append(message.message_id)
        return True

    async def mark_persisted(self, _messages):
        raise AssertionError("failed batch must not be acked")


def _pending_payload() -> QuizQuestionPayload:
    return QuizQuestionPayload(
        session_id=1,
        question_token="tok1",
        question_id="q1",
        question_text="Was ist korrekt?",
        answer_options=(("a1", "Antwort A"), ("a2", "Antwort B")),
        correct_answer="a2",
        explanation="Richtig erklaert.",
        position=1,
        total_questions=5,
        level="A1",
        theme="Alltag",
        correct_answer_text="Antwort B",
        theme_key="alltag",
        content_version="1.0",
        metadata_snapshot={"catalog_id": "cat", "theme_id": "T01", "available_items_count": 10},
        question_reference_id=1,
        training_session_item_id=11,
        user_id=1,
        telegram_user_id=700001,
        session_type="regular",
        answered_count=0,
        correct_answers=0,
    )


def _expected_result() -> AnswerResult:
    return AnswerResult(
        selected_answer="a1",
        correct_answer="a2",
        question_token="tok1",
        is_correct=False,
        is_duplicate=False,
        is_completed=False,
        explanation="Richtig erklaert.",
        correct_answers=0,
        total_questions=5,
        session_id=1,
        correct_answer_text="Antwort B",
        weak_theme=None,
        new_mistakes_count=0,
        recommendation_text=None,
    )


def _persistable_event() -> PersistableAnswerEvent:
    return PersistableAnswerEvent(
        answer_event_id="update:9001",
        telegram_update_id=9001,
        callback_query_id="cbq-9001",
        telegram_user_id=700001,
        user_id=1,
        session_id=1,
        session_item_id=11,
        question_reference_id=1,
        catalog_id="cat",
        item_id="q1",
        item_version="1.0",
        level="A1",
        theme="Alltag",
        theme_id="T01",
        theme_key="alltag",
        selected_answer="a1",
        correct_answer="a2",
        is_correct=False,
        session_type="regular",
        metadata_snapshot={"catalog_id": "cat"},
        available_items_count=10,
        question_token="tok1",
        position=1,
        session_completed=False,
        answered_count=1,
        correct_answers=0,
        total_questions=5,
    )
