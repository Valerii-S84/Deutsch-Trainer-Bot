from __future__ import annotations

from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.answers import AnswerContentFields, AnswerCreateData
from app.runtime.timing import timing_span
from app.services.training_answer_state import AnswerContext, AnswerSnapshot
from app.services.training_payloads import QuestionStateError, QuizQuestionPayload


async def create_answer_or_duplicate(
    processor: Any,
    db: AsyncSession,
    context: AnswerContext,
    snapshot: AnswerSnapshot,
    *,
    is_correct: bool,
    telegram_update_id: int | None,
) -> Any:
    if hasattr(processor._service._answer_repo, "create_idempotent"):
        return await _idempotent_answer_or_duplicate(
            processor,
            db,
            context,
            snapshot,
            is_correct=is_correct,
            telegram_update_id=telegram_update_id,
        )
    return await _legacy_answer_or_duplicate(
        processor,
        db,
        context,
        snapshot,
        is_correct=is_correct,
        telegram_update_id=telegram_update_id,
    )


async def _idempotent_answer_or_duplicate(
    processor: Any,
    db: AsyncSession,
    context: AnswerContext,
    snapshot: AnswerSnapshot,
    *,
    is_correct: bool,
    telegram_update_id: int | None,
) -> Any:
    with timing_span("answer.insert_upsert_ms"):
        answer = await processor._service._answer_repo.create_idempotent(
            db,
            _answer_data_from_snapshot(
                snapshot,
                quiz_source=processor._service.QUIZ_SOURCE,
                is_correct=is_correct,
                telegram_update_id=telegram_update_id,
            ),
        )
    if not answer.created:
        if answer.user_id != snapshot.user_id or answer.session_id != snapshot.session_id:
            raise QuestionStateError("Duplicate answer belongs to another session")
        return await processor._build_duplicate_result(db, snapshot, answer)
    with timing_span("answer.session_item_update_ms"):
        await processor._mark_session_item_answered(db, context)
    return answer


async def _legacy_answer_or_duplicate(
    processor: Any,
    db: AsyncSession,
    context: AnswerContext,
    snapshot: AnswerSnapshot,
    *,
    is_correct: bool,
    telegram_update_id: int | None,
) -> Any:
    if hasattr(db, "begin_nested"):
        return await _legacy_answer_with_savepoint(
            processor,
            db,
            context,
            snapshot,
            is_correct=is_correct,
            telegram_update_id=telegram_update_id,
        )
    return await _legacy_answer_without_savepoint(
        processor,
        db,
        context,
        snapshot,
        is_correct=is_correct,
        telegram_update_id=telegram_update_id,
    )


async def _legacy_answer_with_savepoint(
    processor: Any,
    db: AsyncSession,
    context: AnswerContext,
    snapshot: AnswerSnapshot,
    *,
    is_correct: bool,
    telegram_update_id: int | None,
) -> Any:
    try:
        async with db.begin_nested():
            answer = await _create_answer(processor, db, context, is_correct, telegram_update_id)
            await processor._mark_session_item_answered(db, context)
            await db.flush()
            return answer
    except IntegrityError as exc:
        return await processor._duplicate_after_integrity_error(
            db,
            snapshot,
            telegram_update_id,
            exc,
            rollback=False,
        )


async def _legacy_answer_without_savepoint(
    processor: Any,
    db: AsyncSession,
    context: AnswerContext,
    snapshot: AnswerSnapshot,
    *,
    is_correct: bool,
    telegram_update_id: int | None,
) -> Any:
    try:
        answer = await _create_answer(processor, db, context, is_correct, telegram_update_id)
        await processor._mark_session_item_answered(db, context)
        await db.flush()
        return answer
    except IntegrityError as exc:
        return await processor._duplicate_after_integrity_error(db, snapshot, telegram_update_id, exc)


async def _create_answer(
    processor: Any,
    db: AsyncSession,
    context: AnswerContext,
    is_correct: bool,
    telegram_update_id: int | None,
) -> Any:
    service = processor._service
    data = _answer_data_from_context(
        context,
        quiz_source=service.QUIZ_SOURCE,
        session_type=service._session_flow(context.session),
        is_correct=is_correct,
        telegram_update_id=telegram_update_id,
    )
    answer = await service._answer_repo.create(db, **_answer_create_kwargs(data))
    return _with_catalog_answer_fields(answer, context.pending)


def _answer_data_from_snapshot(
    snapshot: AnswerSnapshot,
    *,
    quiz_source: str,
    is_correct: bool,
    telegram_update_id: int | None,
) -> AnswerCreateData:
    return AnswerCreateData(
        session_id=snapshot.session_id,
        user_id=snapshot.user_id,
        external_quiz_id=snapshot.pending.question_id,
        selected_answer=snapshot.selected_option_id,
        correct_answer=snapshot.pending.correct_answer,
        is_correct=is_correct,
        training_session_item_id=snapshot.pending.training_session_item_id,
        question_reference_id=snapshot.pending.question_reference_id,
        content_fields=_answer_content_fields(snapshot.pending, quiz_source=quiz_source),
        session_type=snapshot.session_type,
        metadata_snapshot=snapshot.pending.metadata_snapshot,
        telegram_update_id=telegram_update_id,
    )


def _answer_data_from_context(
    context: AnswerContext,
    *,
    quiz_source: str,
    session_type: str,
    is_correct: bool,
    telegram_update_id: int | None,
) -> AnswerCreateData:
    return AnswerCreateData(
        session_id=context.session.id,
        user_id=context.user.id,
        external_quiz_id=context.pending.question_id,
        selected_answer=context.selected_option_id,
        correct_answer=context.pending.correct_answer,
        is_correct=is_correct,
        training_session_item_id=context.pending.training_session_item_id,
        question_reference_id=context.pending.question_reference_id,
        content_fields=_answer_content_fields(context.pending, quiz_source=quiz_source),
        session_type=session_type,
        metadata_snapshot=context.pending.metadata_snapshot,
        telegram_update_id=telegram_update_id,
    )


def _answer_content_fields(pending: QuizQuestionPayload, *, quiz_source: str) -> AnswerContentFields:
    return AnswerContentFields(
        catalog_id=_catalog_id_from_metadata(pending.metadata_snapshot),
        item_id=pending.question_id,
        item_version=pending.content_version,
        quiz_source=quiz_source,
        level=pending.level,
        theme=pending.theme,
        theme_key=pending.theme_key,
    )


def _answer_create_kwargs(data: AnswerCreateData) -> dict[str, Any]:
    return {
        "session_id": data.session_id,
        "user_id": data.user_id,
        "external_quiz_id": data.external_quiz_id,
        "selected_answer": data.selected_answer,
        "correct_answer": data.correct_answer,
        "is_correct": data.is_correct,
        "training_session_item_id": data.training_session_item_id,
        "question_reference_id": data.question_reference_id,
        "content_fields": data.content_fields,
        "session_type": data.session_type,
        "metadata_snapshot": data.metadata_snapshot,
        "telegram_update_id": data.telegram_update_id,
    }


def _with_catalog_answer_fields(answer: Any, pending: QuizQuestionPayload) -> Any:
    answer.catalog_id = _catalog_id_from_metadata(pending.metadata_snapshot)
    answer.item_id = pending.question_id
    answer.item_version = pending.content_version
    return answer


def _catalog_id_from_metadata(metadata_snapshot: dict[str, object] | None) -> str | None:
    value = (metadata_snapshot or {}).get("catalog_id")
    return value if isinstance(value, str) and value else None
