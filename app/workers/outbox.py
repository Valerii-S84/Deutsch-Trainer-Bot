from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from socket import gethostname
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import OutboxEvent
from app.db.session import WorkerSessionLocal
from app.repositories.analytics_events import AnalyticsEventRepository
from app.repositories.outbox import OUTBOX_PROCESSING, OutboxRepository
from app.runtime.timing import timing_span
from app.services.analytics import AnalyticsTracker
from app.services.mistakes import MistakeService
from app.services.progress import ProgressService
from app.services.user_identity import ResolvedUserId

logger = logging.getLogger(__name__)

ANSWER_ACCEPTED_EVENT = "answer.accepted"


@dataclass(frozen=True)
class AnswerAcceptedPayload:
    telegram_user_id: int
    user_id: int
    session_id: int
    answer_id: int
    level: str
    theme: str | None
    item_id: str
    selected_answer: str
    correct_answer: str
    is_correct: bool
    session_type: str
    metadata_snapshot: dict[str, object] | None
    theme_key: str | None
    available_items_count: int | None
    question_token: str | None
    position: int | None
    session_completed: bool
    answered_count: int | None
    correct_answers: int | None
    total_questions: int | None


class OutboxEventProcessor:
    """Dispatch durable outbox events to idempotent DB-only side effects."""

    def __init__(
        self,
        *,
        progress_service: ProgressService | None = None,
        mistakes_service: MistakeService | None = None,
        analytics_tracker: AnalyticsTracker | None = None,
    ) -> None:
        self._progress_service = progress_service or ProgressService()
        self._mistakes_service = mistakes_service or MistakeService()
        self._analytics_tracker = analytics_tracker or AnalyticsTracker(AnalyticsEventRepository())

    async def process(self, db: AsyncSession, event: OutboxEvent) -> None:
        if event.event_type == ANSWER_ACCEPTED_EVENT:
            await self._process_answer_accepted(db, _parse_answer_accepted_payload(event.payload))
            return
        raise ValueError(f"Unsupported outbox event type: {event.event_type}")

    async def _process_answer_accepted(self, db: AsyncSession, payload: AnswerAcceptedPayload) -> None:
        with timing_span("worker.mistake_ms"):
            await self._record_mistake_state(db, payload)
        with timing_span("worker.progress_ms"):
            await self._record_progress(db, payload)
        with timing_span("worker.analytics_ms"):
            await self._record_answer_analytics(db, payload)

    async def _record_progress(self, db: AsyncSession, payload: AnswerAcceptedPayload) -> None:
        await self._progress_service.record_answer_result(
            db,
            ResolvedUserId(payload.user_id),
            level=payload.level,
            theme=payload.theme,
            is_correct=payload.is_correct,
            is_duplicate=False,
            session_id=payload.session_id,
            user_answer_id=payload.answer_id,
            item_id=payload.item_id,
            theme_key=payload.theme_key,
            available_items_count=payload.available_items_count,
            metadata_snapshot=payload.metadata_snapshot,
            reason_code="answer_accepted",
        )

    async def _record_mistake_state(self, db: AsyncSession, payload: AnswerAcceptedPayload) -> None:
        if payload.is_correct and payload.session_type == "mistake_review":
            await self._mistakes_service.record_review_success(
                db,
                ResolvedUserId(payload.user_id),
                external_quiz_id=payload.item_id,
                question_level=payload.level,
                question_theme=payload.theme,
                correct_answer=payload.correct_answer,
                session_id=payload.session_id,
                user_answer_id=payload.answer_id,
                metadata_snapshot=payload.metadata_snapshot,
            )
            return
        if payload.is_correct:
            return
        await self._mistakes_service.record_wrong_answer(
            db,
            ResolvedUserId(payload.user_id),
            external_quiz_id=payload.item_id,
            level=payload.level,
            theme=payload.theme,
            wrong_answer=payload.selected_answer,
            correct_answer=payload.correct_answer,
            source_snapshot={
                "session_type": payload.session_type,
                "question_token": payload.question_token,
                "metadata_snapshot": payload.metadata_snapshot,
            },
            session_id=payload.session_id,
            user_answer_id=payload.answer_id,
            metadata_snapshot=payload.metadata_snapshot,
        )

    async def _record_answer_analytics(self, db: AsyncSession, payload: AnswerAcceptedPayload) -> None:
        answer_metadata = {
            "session_type": payload.session_type,
            "level": payload.level,
            "theme": payload.theme,
            "item_id": payload.item_id,
            "is_correct": payload.is_correct,
            "position": payload.position,
        }
        events = [
            {
                "event_name": "question_answered",
                "user_id": payload.user_id,
                "session_id": payload.session_id,
                "event_metadata": answer_metadata,
                "source": "training",
            },
        ]
        if not payload.session_completed:
            await self._analytics_tracker.record_many(db, events)
            return
        completion_metadata = {
            "session_type": payload.session_type,
            "level": payload.level,
            "theme": payload.theme,
            "answered_count": payload.answered_count,
            "correct_answers": payload.correct_answers,
            "planned_question_count": payload.total_questions,
        }
        events.extend(
            [
                {
                    "event_name": "training_completed",
                    "user_id": payload.user_id,
                    "session_id": payload.session_id,
                    "event_metadata": completion_metadata,
                    "source": "training",
                },
                {
                    "event_name": "result_shown",
                    "user_id": payload.user_id,
                    "session_id": payload.session_id,
                    "event_metadata": completion_metadata,
                    "source": "training",
                },
            ],
        )
        await self._analytics_tracker.record_many(db, events)


class OutboxWorker:
    """Claim and process outbox events with bounded batches."""

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession] = WorkerSessionLocal,
        outbox_repo: OutboxRepository | None = None,
        processor: OutboxEventProcessor | None = None,
        worker_id: str | None = None,
        batch_size: int = 200,
        max_parallelism: int = 5,
        stale_after_seconds: int = 300,
    ) -> None:
        self._session_factory = session_factory
        self._outbox_repo = outbox_repo or OutboxRepository()
        self._processor = processor or OutboxEventProcessor()
        self._worker_id = worker_id or f"{gethostname()}:{uuid4().hex[:12]}"
        self._batch_size = batch_size
        self._max_parallelism = max(1, max_parallelism)
        self._stale_after_seconds = stale_after_seconds

    async def process_once(self) -> int:
        events = await self._claim_events()
        if not events:
            return 0

        if self._max_parallelism <= 1 or len(events) <= 1:
            for event in events:
                await self._process_event(event)
            return len(events)

        semaphore = asyncio.Semaphore(self._max_parallelism)

        async def _bounded_process(event: OutboxEvent) -> None:
            async with semaphore:
                await self._process_event(event)

        await asyncio.gather(*(_bounded_process(event) for event in events))
        return len(events)

    async def run_forever(self, *, idle_sleep_seconds: float = 1.0) -> None:
        while True:
            processed = await self.process_once()
            if processed == 0:
                await asyncio.sleep(idle_sleep_seconds)

    async def lag_seconds(self) -> float:
        async with self._session_factory() as db:
            return await self._outbox_repo.pending_lag_seconds(db)

    async def _claim_events(self) -> list[OutboxEvent]:
        async with self._session_factory() as db:
            await self._outbox_repo.requeue_stale_processing(
                db,
                stale_after_seconds=self._stale_after_seconds,
            )
            events = await self._outbox_repo.claim_batch(
                db,
                worker_id=self._worker_id,
                batch_size=self._batch_size,
            )
            await db.commit()
            return events

    async def _process_event(self, event: OutboxEvent) -> None:
        try:
            async with self._session_factory() as db:
                await self._processor.process(db, event)
                await self._outbox_repo.mark_done_by_id(db, event.id)
                await db.commit()
        except Exception as exc:
            logger.exception("outbox event processing failed: event_id=%s", event.id)
            await self._mark_failed(event.id, str(exc))

    async def _mark_failed(self, event_id: int, error_message: str) -> None:
        async with self._session_factory() as db:
            await self._outbox_repo.mark_failed_by_id(db, event_id, error_message=error_message)
            await db.commit()


def _required_int(payload: dict[str, object], key: str) -> int:
    value = payload.get(key)
    if not isinstance(value, int):
        raise ValueError(f"Outbox payload field must be int: {key}")
    return value


def _optional_int(payload: dict[str, object], key: str) -> int | None:
    value = payload.get(key)
    return value if isinstance(value, int) else None


def _required_str(payload: dict[str, object], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"Outbox payload field must be non-empty string: {key}")
    return value


def _optional_str(payload: dict[str, object], key: str) -> str | None:
    value = payload.get(key)
    return value if isinstance(value, str) and value else None


def _required_bool(payload: dict[str, object], key: str) -> bool:
    value = payload.get(key)
    if not isinstance(value, bool):
        raise ValueError(f"Outbox payload field must be bool: {key}")
    return value


def _optional_dict(payload: dict[str, object], key: str) -> dict[str, object] | None:
    value = payload.get(key)
    return value if isinstance(value, dict) else None


def _parse_answer_accepted_payload(payload: dict[str, object]) -> AnswerAcceptedPayload:
    return AnswerAcceptedPayload(
        telegram_user_id=_required_int(payload, "telegram_user_id"),
        user_id=_required_int(payload, "user_id"),
        session_id=_required_int(payload, "session_id"),
        answer_id=_required_int(payload, "answer_id"),
        level=_required_str(payload, "level"),
        theme=_optional_str(payload, "theme"),
        item_id=_required_str(payload, "item_id"),
        selected_answer=_required_str(payload, "selected_answer"),
        correct_answer=_required_str(payload, "correct_answer"),
        is_correct=_required_bool(payload, "is_correct"),
        session_type=_required_str(payload, "session_type"),
        metadata_snapshot=_optional_dict(payload, "metadata_snapshot"),
        theme_key=_optional_str(payload, "theme_key"),
        available_items_count=_optional_int(payload, "available_items_count"),
        question_token=_optional_str(payload, "question_token"),
        position=_optional_int(payload, "position"),
        session_completed=_required_bool(payload, "session_completed"),
        answered_count=_optional_int(payload, "answered_count"),
        correct_answers=_optional_int(payload, "correct_answers"),
        total_questions=_optional_int(payload, "total_questions"),
    )
