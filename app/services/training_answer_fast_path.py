from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import QuizSession, TrainingSessionItem, User
from app.repositories.answers import AnswerContentFields, AnswerCreateData, AnswerWriteResult
from app.runtime.timing import timing_span
from app.services.training_payloads import (
    ActiveSessionNotFoundError,
    AnswerResult,
    QuestionStateError,
    QuizQuestionPayload,
    deserialize_question_payload,
    option_ids,
    option_text,
)


ANSWER_ACCEPTED_EVENT = "answer.accepted"
ACTIVE_SESSION_STATUS = "active"
COMPLETED_SESSION_STATUS = "completed"


@dataclass(frozen=True)
class FastPathContext:
    telegram_user_id: int
    user_id: int
    session_id: int
    session_type: str
    total_questions: int
    answered_count: int
    correct_answers: int
    pending: QuizQuestionPayload
    selected_option_id: str
    correct_answer_text: str
    api_metadata: dict[str, object]


@dataclass(frozen=True)
class SessionState:
    answered_count: int
    correct_answers: int
    total_questions: int
    completed: bool


async def accept_answer_fast_path(
    service: Any,
    db: AsyncSession,
    telegram_user_id: int,
    session_id: int,
    question_token: str,
    selected_option_id: str,
    telegram_update_id: int | None,
) -> AnswerResult | None:
    if _dialect_name(db) != "postgresql":
        return None

    with timing_span("answer.validate_ms"):
        context = await _validate_context(
            db,
            telegram_user_id=telegram_user_id,
            session_id=session_id,
            question_token=question_token,
            selected_option_id=selected_option_id,
        )

    is_correct = selected_option_id == context.pending.correct_answer
    with timing_span("answer.insert_upsert_ms"):
        answer = await service._answer_repo.create_idempotent(
            db,
            _answer_data(context, is_correct=is_correct, telegram_update_id=telegram_update_id),
        )

    if not answer.created:
        if answer.user_id != context.user_id or answer.session_id != context.session_id:
            raise QuestionStateError("Duplicate answer belongs to another session")
        session_state = await _current_session_state(db, session_id=context.session_id)
        return _duplicate_result(context, session_state, answer)

    with timing_span("answer.session_item_update_ms"):
        await _mark_session_item_answered(db, context)

    with timing_span("answer.session_update_ms"):
        session_state = await _update_session_state(db, context, is_correct=is_correct)

    with timing_span("answer.response_formatting_ms"):
        result = _accepted_result(context, session_state, is_correct=is_correct)

    with timing_span("answer.outbox_insert_ms"):
        await service._outbox_repo.enqueue(
            db,
            event_type=ANSWER_ACCEPTED_EVENT,
            aggregate_type="user_answer",
            aggregate_id=answer.id,
            idempotency_key=f"{ANSWER_ACCEPTED_EVENT}:{answer.id}",
            payload=_answer_accepted_payload(context, session_state, answer=answer, is_correct=is_correct, result=result),
        )

    return result


async def _validate_context(
    db: AsyncSession,
    *,
    telegram_user_id: int,
    session_id: int,
    question_token: str,
    selected_option_id: str,
) -> FastPathContext:
    row = (
        await db.execute(
            select(
                User.id.label("user_id"),
                User.telegram_user_id.label("telegram_user_id"),
                QuizSession.id.label("session_id"),
                QuizSession.status.label("status"),
                QuizSession.session_type.label("session_type"),
                QuizSession.source_metadata.label("source_metadata"),
                QuizSession.total_questions.label("total_questions"),
                QuizSession.answered_count.label("answered_count"),
                QuizSession.correct_answers.label("correct_answers"),
                QuizSession.api_metadata.label("api_metadata"),
            )
            .join(User, User.id == QuizSession.user_id)
            .where(User.telegram_user_id == telegram_user_id)
            .where(QuizSession.id == session_id)
        )
    ).mappings().first()
    if row is None:
        raise ActiveSessionNotFoundError("Session is not found")
    if str(row["status"]) != ACTIVE_SESSION_STATUS:
        raise ActiveSessionNotFoundError("Session is not active")

    metadata = row["api_metadata"] if isinstance(row["api_metadata"], dict) else {}
    pending_raw = metadata.get("pending_question")
    if not isinstance(pending_raw, dict):
        raise QuestionStateError("No active question in session")
    pending = deserialize_question_payload(pending_raw)
    if pending.question_token != question_token or pending.session_id != int(row["session_id"]):
        raise QuestionStateError("Question token is stale")
    if selected_option_id not in option_ids(pending):
        raise QuestionStateError("Selected answer is invalid")

    return FastPathContext(
        telegram_user_id=int(row["telegram_user_id"]),
        user_id=int(row["user_id"]),
        session_id=int(row["session_id"]),
        session_type=_session_type(row["session_type"], row["source_metadata"]),
        total_questions=int(row["total_questions"]),
        answered_count=int(row["answered_count"] or 0),
        correct_answers=int(row["correct_answers"] or 0),
        pending=pending,
        selected_option_id=selected_option_id,
        correct_answer_text=pending.correct_answer_text or option_text(pending, pending.correct_answer),
        api_metadata=metadata,
    )


async def _mark_session_item_answered(db: AsyncSession, context: FastPathContext) -> None:
    now = datetime.now(UTC)
    if context.pending.training_session_item_id is not None:
        await db.execute(
            update(TrainingSessionItem)
            .where(TrainingSessionItem.id == context.pending.training_session_item_id)
            .values(
                status="answered",
                answered_at=now,
                updated_at=now,
            )
        )
        return

    await db.execute(
        update(TrainingSessionItem)
        .where(TrainingSessionItem.session_id == context.session_id)
        .where(TrainingSessionItem.item_id == context.pending.question_id)
        .values(
            status="answered",
            answered_at=now,
            updated_at=now,
        )
    )


async def _update_session_state(
    db: AsyncSession,
    context: FastPathContext,
    *,
    is_correct: bool,
) -> SessionState:
    answered_count = context.answered_count + 1
    correct_answers = context.correct_answers + (1 if is_correct else 0)
    completed = answered_count >= context.total_questions
    now = datetime.now(UTC)
    values: dict[str, object] = {
        "answered_count": answered_count,
        "updated_at": now,
    }
    if is_correct:
        values["correct_answers"] = correct_answers
    if completed:
        session_metadata = dict(context.api_metadata)
        session_metadata.pop("pending_question", None)
        values.update(
            status=COMPLETED_SESSION_STATUS,
            finished_at=now,
            completed_at=now,
            api_metadata=session_metadata,
        )
    await db.execute(
        update(QuizSession)
        .where(QuizSession.id == context.session_id)
        .values(**values)
    )
    return SessionState(
        answered_count=answered_count,
        correct_answers=correct_answers,
        total_questions=context.total_questions,
        completed=completed,
    )


async def _current_session_state(db: AsyncSession, *, session_id: int) -> SessionState:
    row = (
        await db.execute(
            select(
                QuizSession.answered_count,
                QuizSession.correct_answers,
                QuizSession.total_questions,
                QuizSession.status,
            ).where(QuizSession.id == session_id)
        )
    ).one()
    return SessionState(
        answered_count=int(row.answered_count or 0),
        correct_answers=int(row.correct_answers or 0),
        total_questions=int(row.total_questions or 0),
        completed=str(row.status) == COMPLETED_SESSION_STATUS or int(row.answered_count or 0) >= int(row.total_questions or 0),
    )


def _accepted_result(
    context: FastPathContext,
    session_state: SessionState,
    *,
    is_correct: bool,
) -> AnswerResult:
    recommendation_text = "Starte eine neue Runde, um weiter zu üben." if session_state.completed else None
    return AnswerResult(
        selected_answer=context.selected_option_id,
        correct_answer=context.pending.correct_answer,
        question_token=context.pending.question_token,
        is_correct=is_correct,
        is_duplicate=False,
        is_completed=session_state.completed,
        explanation=context.pending.explanation,
        correct_answers=session_state.correct_answers,
        total_questions=session_state.total_questions,
        session_id=context.session_id,
        correct_answer_text=context.correct_answer_text,
        weak_theme=None,
        new_mistakes_count=0,
        recommendation_text=recommendation_text,
    )


def _duplicate_result(
    context: FastPathContext,
    session_state: SessionState,
    answer: AnswerWriteResult,
) -> AnswerResult:
    return AnswerResult(
        selected_answer=context.selected_option_id,
        correct_answer=context.pending.correct_answer,
        question_token=context.pending.question_token,
        is_correct=answer.is_correct,
        is_duplicate=True,
        is_completed=session_state.completed,
        explanation=context.pending.explanation,
        correct_answers=session_state.correct_answers,
        total_questions=session_state.total_questions,
        session_id=context.session_id,
        correct_answer_text=context.correct_answer_text,
    )


def _answer_accepted_payload(
    context: FastPathContext,
    session_state: SessionState,
    *,
    answer: AnswerWriteResult,
    is_correct: bool,
    result: AnswerResult,
) -> dict[str, object]:
    answer_id = int(answer.id)
    return {
        "answer_id": answer_id,
        "telegram_user_id": context.telegram_user_id,
        "user_id": context.user_id,
        "session_id": context.session_id,
        "session_item_id": context.pending.training_session_item_id,
        "question_token": context.pending.question_token,
        "catalog_id": _catalog_id(context.pending.metadata_snapshot),
        "item_id": context.pending.question_id,
        "item_version": context.pending.content_version,
        "level": context.pending.level,
        "theme": context.pending.theme,
        "theme_id": _theme_id(context.pending),
        "theme_key": context.pending.theme_key,
        "selected_answer": context.selected_option_id,
        "correct_answer": context.pending.correct_answer,
        "is_correct": is_correct,
        "session_type": context.session_type,
        "answered_at": _answered_at_iso(answer),
        "position": context.pending.position,
        "available_items_count": _available_count(context.pending.metadata_snapshot),
        "metadata_snapshot": context.pending.metadata_snapshot,
        "session_completed": result.is_completed,
        "answered_count": session_state.answered_count,
        "correct_answers": result.correct_answers,
        "total_questions": result.total_questions,
    }


def _answer_data(
    context: FastPathContext,
    *,
    is_correct: bool,
    telegram_update_id: int | None,
) -> AnswerCreateData:
    return AnswerCreateData(
        session_id=context.session_id,
        user_id=context.user_id,
        external_quiz_id=context.pending.question_id,
        selected_answer=context.selected_option_id,
        correct_answer=context.pending.correct_answer,
        is_correct=is_correct,
        training_session_item_id=context.pending.training_session_item_id,
        question_reference_id=context.pending.question_reference_id,
        content_fields=AnswerContentFields(
            catalog_id=_catalog_id(context.pending.metadata_snapshot),
            item_id=context.pending.question_id,
            item_version=context.pending.content_version,
            quiz_source="local_quiz_catalog",
            level=context.pending.level,
            theme=context.pending.theme,
            theme_key=context.pending.theme_key,
        ),
        session_type=context.session_type,
        metadata_snapshot=context.pending.metadata_snapshot,
        telegram_update_id=telegram_update_id,
    )


def _session_type(session_type: object, source_metadata: object) -> str:
    if isinstance(source_metadata, dict):
        flow = source_metadata.get("flow")
        if isinstance(flow, str) and flow:
            return flow
    if isinstance(session_type, str) and session_type:
        return session_type
    return "regular"


def _available_count(metadata_snapshot: dict[str, object] | None) -> int | None:
    if metadata_snapshot is None:
        return None
    value = metadata_snapshot.get("available_items_count")
    return value if isinstance(value, int) and value >= 0 else None


def _catalog_id(metadata_snapshot: dict[str, object] | None) -> str | None:
    if metadata_snapshot is None:
        return None
    value = metadata_snapshot.get("catalog_id")
    return value if isinstance(value, str) and value else None


def _theme_id(pending: QuizQuestionPayload) -> str | None:
    metadata = pending.metadata_snapshot or {}
    value = metadata.get("theme_id")
    if isinstance(value, str) and value:
        return value
    return pending.theme_key


def _answered_at_iso(answer: AnswerWriteResult) -> str | None:
    answered_at = answer.answered_at or datetime.now(UTC)
    return answered_at.isoformat()


def _dialect_name(db: AsyncSession) -> str:
    get_bind = getattr(db, "get_bind", None)
    if get_bind is None:
        return ""
    bind = get_bind()
    return bind.dialect.name if bind is not None else ""
