from __future__ import annotations

import asyncio
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
import logging
from socket import gethostname
from uuid import uuid4

import sqlalchemy as sa
from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import OutboxEvent, QuizSession, TrainingSessionItem, UserAnswer
from app.db.session import WorkerSessionLocal
from app.runtime.answer_persistence_queue import (
    AnswerPersistenceMessage,
    AnswerPersistenceQueue,
    AnswerPersistenceQueueError,
)

logger = logging.getLogger(__name__)

ANSWER_ACCEPTED_EVENT = "answer.accepted"
ANSWER_AGGREGATE_TYPE = "user_answer"


@dataclass(frozen=True, slots=True)
class PersistableAnswerEvent:
    answer_event_id: str
    telegram_update_id: int | None
    callback_query_id: str | None
    telegram_user_id: int
    user_id: int
    session_id: int
    session_item_id: int | None
    question_reference_id: int | None
    catalog_id: str | None
    item_id: str
    item_version: str | None
    level: str
    theme: str | None
    theme_id: str | None
    theme_key: str | None
    selected_answer: str
    correct_answer: str
    is_correct: bool
    session_type: str
    metadata_snapshot: dict[str, object] | None
    available_items_count: int | None
    question_token: str | None
    position: int | None
    session_completed: bool
    answered_count: int
    correct_answers: int
    total_questions: int


class AnswerPersistenceWorker:
    """Flush Redis answer events to PostgreSQL in batches."""

    def __init__(
        self,
        *,
        queue: AnswerPersistenceQueue,
        session_factory: Callable[[], AsyncSession] = WorkerSessionLocal,
        consumer_name: str | None = None,
        batch_size: int = 250,
        flush_interval_ms: int = 100,
        stale_idle_ms: int = 60_000,
        max_attempts: int = 5,
    ) -> None:
        self._queue = queue
        self._session_factory = session_factory
        self._consumer_name = consumer_name or f"{gethostname()}:{uuid4().hex[:12]}"
        self._batch_size = max(1, batch_size)
        self._flush_interval_ms = max(1, flush_interval_ms)
        self._stale_idle_ms = max(1, stale_idle_ms)
        self._max_attempts = max(1, max_attempts)

    async def process_once(self) -> int:
        messages = await self._queue.claim_stale(
            consumer_name=self._consumer_name,
            min_idle_ms=self._stale_idle_ms,
            count=self._batch_size,
        )
        if not messages:
            messages = await self._queue.read_batch(
                consumer_name=self._consumer_name,
                count=self._batch_size,
                block_ms=self._flush_interval_ms,
            )
        if not messages:
            return 0

        try:
            await self._persist_messages(messages)
        except Exception as exc:
            logger.exception("answer persistence batch failed: count=%s", len(messages))
            await asyncio.gather(
                *(
                    self._queue.retry_or_dead(
                        message,
                        max_attempts=self._max_attempts,
                        error_message=f"{exc.__class__.__name__}: {exc}",
                    )
                    for message in messages
                )
            )
            return 0
        await self._queue.mark_persisted(messages)
        return len(messages)

    async def run_forever(self, *, idle_sleep_seconds: float = 0.05) -> None:
        while True:
            try:
                processed = await self.process_once()
            except AnswerPersistenceQueueError:
                logger.exception("answer persistence queue unavailable; retrying")
                await asyncio.sleep(max(1.0, idle_sleep_seconds))
                continue
            if processed == 0:
                await asyncio.sleep(max(0.0, idle_sleep_seconds))

    async def _persist_messages(self, messages: Sequence[AnswerPersistenceMessage]) -> None:
        events = [_parse_event(message.payload, answer_event_id=message.answer_event_id) for message in messages]
        async with self._session_factory() as db:
            async with db.begin():
                await persist_answer_events(db, events)


async def persist_answer_events(db: AsyncSession, events: Sequence[PersistableAnswerEvent]) -> None:
    if not events:
        return
    now = datetime.now(UTC)
    answer_ids = await _insert_answers(db, events, answered_at=now)
    await _mark_session_items_answered(db, events, answered_at=now)
    await _update_sessions(db, events, now=now)
    await _insert_outbox_events(db, events, answer_ids, answered_at=now)


async def _insert_answers(
    db: AsyncSession,
    events: Sequence[PersistableAnswerEvent],
    *,
    answered_at: datetime,
) -> dict[str, int]:
    rows = [_answer_row(event, answered_at=answered_at) for event in events]
    dialect = _dialect_name(db)
    if dialect == "postgresql":
        statement = (
            postgresql_insert(UserAnswer)
            .values(rows)
            .on_conflict_do_nothing()
            .returning(
                UserAnswer.id,
                UserAnswer.telegram_update_id,
                UserAnswer.session_id,
                UserAnswer.user_id,
                UserAnswer.external_quiz_id,
            )
        )
        result = await db.execute(statement)
        answer_ids = _answer_ids_from_rows(result.mappings().all(), events)
        if len(answer_ids) < len(events):
            answer_ids.update(await _load_answer_ids(db, _missing_answer_events(events, answer_ids)))
        return answer_ids
    elif dialect == "sqlite":
        await _assign_sqlite_ids(db, rows, UserAnswer)
        statement = sqlite_insert(UserAnswer).values(rows).on_conflict_do_nothing()
    else:
        statement = sa.insert(UserAnswer).values(rows)
    await db.execute(statement)
    return await _load_answer_ids(db, events)


async def _load_answer_ids(
    db: AsyncSession,
    events: Sequence[PersistableAnswerEvent],
) -> dict[str, int]:
    by_event: dict[str, int] = {}
    update_ids = [event.telegram_update_id for event in events if event.telegram_update_id is not None]
    if update_ids:
        rows = (
            await db.execute(
                select(UserAnswer.id, UserAnswer.telegram_update_id).where(
                    UserAnswer.telegram_update_id.in_(update_ids),
                ),
            )
        ).all()
        by_update_id = {
            int(row.telegram_update_id): int(row.id)
            for row in rows
            if row.telegram_update_id is not None
        }
        for event in events:
            if event.telegram_update_id is not None and event.telegram_update_id in by_update_id:
                by_event[event.answer_event_id] = by_update_id[event.telegram_update_id]

    missing = _missing_answer_events(events, by_event)
    for event in missing:
        answer_id = await db.scalar(
            select(UserAnswer.id)
            .where(UserAnswer.session_id == event.session_id)
            .where(UserAnswer.user_id == event.user_id)
            .where(UserAnswer.external_quiz_id == event.item_id)
        )
        if answer_id is None:
            raise RuntimeError(f"Answer was not persisted for event {event.answer_event_id}")
        by_event[event.answer_event_id] = int(answer_id)
    return by_event


async def _mark_session_items_answered(
    db: AsyncSession,
    events: Sequence[PersistableAnswerEvent],
    *,
    answered_at: datetime,
) -> None:
    item_ids = [event.session_item_id for event in events if event.session_item_id is not None]
    if not item_ids:
        return
    await db.execute(
        update(TrainingSessionItem)
        .where(TrainingSessionItem.id.in_(item_ids))
        .values(status="answered", answered_at=answered_at, updated_at=answered_at)
    )


async def _update_sessions(
    db: AsyncSession,
    events: Sequence[PersistableAnswerEvent],
    *,
    now: datetime,
) -> None:
    if _dialect_name(db) == "postgresql":
        await _update_sessions_postgresql(db, events, now=now)
        return
    for event in events:
        values: dict[str, object] = {
            "answered_count": event.answered_count,
            "correct_answers": event.correct_answers,
            "updated_at": now,
        }
        if event.session_completed:
            values.update(status="completed", finished_at=now, completed_at=now)
        await db.execute(update(QuizSession).where(QuizSession.id == event.session_id).values(**values))


async def _update_sessions_postgresql(
    db: AsyncSession,
    events: Sequence[PersistableAnswerEvent],
    *,
    now: datetime,
) -> None:
    latest_by_session = {event.session_id: event for event in events}
    rows = [
        (
            event.session_id,
            event.answered_count,
            event.correct_answers,
            event.session_completed,
        )
        for event in latest_by_session.values()
    ]
    if not rows:
        return
    updates = sa.values(
        sa.column("session_id", sa.BigInteger),
        sa.column("answered_count", sa.Integer),
        sa.column("correct_answers", sa.Integer),
        sa.column("session_completed", sa.Boolean),
        name="session_updates",
    ).data(rows)
    statement = (
        update(QuizSession)
        .where(QuizSession.id == updates.c.session_id)
        .values(
            answered_count=updates.c.answered_count,
            correct_answers=updates.c.correct_answers,
            updated_at=now,
            status=sa.case((updates.c.session_completed, "completed"), else_=QuizSession.status),
            finished_at=sa.case((updates.c.session_completed, now), else_=QuizSession.finished_at),
            completed_at=sa.case((updates.c.session_completed, now), else_=QuizSession.completed_at),
        )
    )
    await db.execute(statement)


async def _insert_outbox_events(
    db: AsyncSession,
    events: Sequence[PersistableAnswerEvent],
    answer_ids: dict[str, int],
    *,
    answered_at: datetime,
) -> None:
    rows = []
    for event in events:
        answer_id = answer_ids[event.answer_event_id]
        rows.append(
            {
                "event_type": ANSWER_ACCEPTED_EVENT,
                "aggregate_type": ANSWER_AGGREGATE_TYPE,
                "aggregate_id": answer_id,
                "idempotency_key": f"{ANSWER_ACCEPTED_EVENT}:{answer_id}",
                "payload": _outbox_payload(event, answer_id=answer_id, answered_at=answered_at),
            }
        )
    dialect = _dialect_name(db)
    if dialect == "postgresql":
        statement = (
            postgresql_insert(OutboxEvent)
            .values(rows)
            .on_conflict_do_nothing(index_elements=[OutboxEvent.idempotency_key])
        )
    elif dialect == "sqlite":
        await _assign_sqlite_ids(db, rows, OutboxEvent)
        statement = sqlite_insert(OutboxEvent).values(rows).on_conflict_do_nothing(
            index_elements=[OutboxEvent.idempotency_key],
        )
    else:
        statement = sa.insert(OutboxEvent).values(rows)
    await db.execute(statement)


def _answer_row(event: PersistableAnswerEvent, *, answered_at: datetime) -> dict[str, object]:
    return {
        "session_id": event.session_id,
        "user_id": event.user_id,
        "external_quiz_id": event.item_id,
        "training_session_item_id": event.session_item_id,
        "question_reference_id": event.question_reference_id,
        "catalog_id": event.catalog_id,
        "item_id": event.item_id,
        "item_version": event.item_version,
        "level": event.level,
        "theme": event.theme,
        "theme_key": event.theme_key,
        "selected_answer": event.selected_answer,
        "correct_answer": event.correct_answer,
        "is_correct": event.is_correct,
        "answered_at": answered_at,
        "session_type": event.session_type,
        "metadata_snapshot": event.metadata_snapshot,
        "telegram_update_id": event.telegram_update_id,
        "quiz_source": "local_quiz_catalog",
    }


def _answer_ids_from_rows(
    rows: Sequence[dict[str, object]],
    events: Sequence[PersistableAnswerEvent],
) -> dict[str, int]:
    by_update_id = {
        event.telegram_update_id: event.answer_event_id
        for event in events
        if event.telegram_update_id is not None
    }
    by_identity = {_answer_identity(event): event.answer_event_id for event in events}
    answer_ids: dict[str, int] = {}
    for row in rows:
        event_id = None
        update_id = row.get("telegram_update_id")
        if update_id is not None:
            event_id = by_update_id.get(int(update_id))
        if event_id is None:
            event_id = by_identity.get(
                (
                    int(row["session_id"]),
                    int(row["user_id"]),
                    str(row["external_quiz_id"]),
                ),
            )
        if event_id is not None:
            answer_ids[event_id] = int(row["id"])
    return answer_ids


def _missing_answer_events(
    events: Sequence[PersistableAnswerEvent],
    answer_ids: dict[str, int],
) -> list[PersistableAnswerEvent]:
    return [event for event in events if event.answer_event_id not in answer_ids]


def _answer_identity(event: PersistableAnswerEvent) -> tuple[int, int, str]:
    return event.session_id, event.user_id, event.item_id


def _outbox_payload(
    event: PersistableAnswerEvent,
    *,
    answer_id: int,
    answered_at: datetime,
) -> dict[str, object]:
    return {
        "answer_id": answer_id,
        "telegram_user_id": event.telegram_user_id,
        "user_id": event.user_id,
        "session_id": event.session_id,
        "session_item_id": event.session_item_id,
        "question_token": event.question_token,
        "catalog_id": event.catalog_id,
        "item_id": event.item_id,
        "item_version": event.item_version,
        "level": event.level,
        "theme": event.theme,
        "theme_id": event.theme_id,
        "theme_key": event.theme_key,
        "selected_answer": event.selected_answer,
        "correct_answer": event.correct_answer,
        "is_correct": event.is_correct,
        "session_type": event.session_type,
        "answered_at": answered_at.isoformat(),
        "position": event.position,
        "available_items_count": event.available_items_count,
        "metadata_snapshot": event.metadata_snapshot,
        "session_completed": event.session_completed,
        "answered_count": event.answered_count,
        "correct_answers": event.correct_answers,
        "total_questions": event.total_questions,
    }


def _parse_event(payload: dict[str, object], *, answer_event_id: str) -> PersistableAnswerEvent:
    return PersistableAnswerEvent(
        answer_event_id=answer_event_id or _required_str(payload, "answer_event_id"),
        telegram_update_id=_optional_int(payload, "telegram_update_id"),
        callback_query_id=_optional_str(payload, "callback_query_id"),
        telegram_user_id=_required_int(payload, "telegram_user_id"),
        user_id=_required_int(payload, "user_id"),
        session_id=_required_int(payload, "session_id"),
        session_item_id=_optional_int(payload, "session_item_id"),
        question_reference_id=_optional_int(payload, "question_reference_id"),
        catalog_id=_optional_str(payload, "catalog_id"),
        item_id=_required_str(payload, "item_id"),
        item_version=_optional_str(payload, "item_version"),
        level=_required_str(payload, "level"),
        theme=_optional_str(payload, "theme"),
        theme_id=_optional_str(payload, "theme_id"),
        theme_key=_optional_str(payload, "theme_key"),
        selected_answer=_required_str(payload, "selected_answer"),
        correct_answer=_required_str(payload, "correct_answer"),
        is_correct=_required_bool(payload, "is_correct"),
        session_type=_required_str(payload, "session_type"),
        metadata_snapshot=_optional_dict(payload, "metadata_snapshot"),
        available_items_count=_optional_int(payload, "available_items_count"),
        question_token=_optional_str(payload, "question_token"),
        position=_optional_int(payload, "position"),
        session_completed=_required_bool(payload, "session_completed"),
        answered_count=_required_int(payload, "answered_count"),
        correct_answers=_required_int(payload, "correct_answers"),
        total_questions=_required_int(payload, "total_questions"),
    )


def _required_int(payload: dict[str, object], key: str) -> int:
    value = payload.get(key)
    if not isinstance(value, int):
        raise ValueError(f"Answer persistence field must be int: {key}")
    return value


def _optional_int(payload: dict[str, object], key: str) -> int | None:
    value = payload.get(key)
    return value if isinstance(value, int) else None


def _required_str(payload: dict[str, object], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"Answer persistence field must be non-empty string: {key}")
    return value


def _optional_str(payload: dict[str, object], key: str) -> str | None:
    value = payload.get(key)
    return value if isinstance(value, str) and value else None


def _required_bool(payload: dict[str, object], key: str) -> bool:
    value = payload.get(key)
    if not isinstance(value, bool):
        raise ValueError(f"Answer persistence field must be bool: {key}")
    return value


def _optional_dict(payload: dict[str, object], key: str) -> dict[str, object] | None:
    value = payload.get(key)
    return value if isinstance(value, dict) else None


def _dialect_name(db: AsyncSession) -> str:
    bind = db.get_bind()
    return bind.dialect.name if bind is not None else ""


async def _assign_sqlite_ids(db: AsyncSession, rows: list[dict[str, object]], model: object) -> None:
    if not rows:
        return
    current_max = int((await db.scalar(select(func.max(model.id)))) or 0)  # type: ignore[attr-defined]
    for offset, row in enumerate(rows, start=1):
        row.setdefault("id", current_max + offset)
