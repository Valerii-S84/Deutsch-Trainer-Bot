from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.training_payloads import (
    ActiveSessionNotFoundError,
    AnswerResult,
    QuestionStateError,
    QuizQuestionPayload,
    deserialize_question_payload,
    option_ids,
    option_text,
)


@dataclass(frozen=True)
class _AnswerContext:
    user: Any
    session: Any
    pending: QuizQuestionPayload
    selected_option_id: str
    correct_answer_text: str


class TrainingAnswerProcessor:
    """Accept answers and apply training side effects."""

    def __init__(self, service: Any) -> None:
        self._service = service

    async def submit_answer(
        self,
        db: AsyncSession,
        telegram_user_id: int,
        session_id: int,
        question_token: str,
        selected_option_id: str,
        telegram_update_id: int | None = None,
    ) -> AnswerResult:
        context = await self._validate_pending_answer(
            db,
            telegram_user_id,
            session_id,
            question_token,
            selected_option_id,
        )
        duplicate = await self._duplicate_result(db, context, telegram_update_id)
        if duplicate is not None:
            return duplicate

        is_correct = selected_option_id == context.pending.correct_answer
        answer = await self._create_answer_or_duplicate(
            db,
            context,
            is_correct=is_correct,
            telegram_update_id=telegram_update_id,
        )
        if isinstance(answer, AnswerResult):
            return answer

        await self._apply_session_counters(db, context, is_correct=is_correct)
        new_mistakes_count = await self._record_learning_side_effects(
            db,
            context,
            answer=answer,
            is_correct=is_correct,
        )
        await self._record_question_answered(db, context, is_correct=is_correct)
        return await self._complete_and_build_result(
            db,
            context,
            is_correct=is_correct,
            new_mistakes_count=new_mistakes_count,
        )

    async def _validate_pending_answer(
        self,
        db: AsyncSession,
        telegram_user_id: int,
        session_id: int,
        question_token: str,
        selected_option_id: str,
    ) -> _AnswerContext:
        service = self._service
        user = await service.get_user(db, telegram_user_id)
        session = await service._session_repo.get_by_id_for_user(db, session_id, user.id)
        if not session:
            raise ActiveSessionNotFoundError("Session is not found")
        if session.status != service.ACTIVE_SESSION_STATUS:
            raise ActiveSessionNotFoundError("Session is not active")

        pending = self._pending_answer_payload(session)
        if pending.question_token != question_token or pending.session_id != session.id:
            raise QuestionStateError("Question token is stale")
        if selected_option_id not in option_ids(pending):
            raise QuestionStateError("Selected answer is invalid")

        correct_answer_text = pending.correct_answer_text or option_text(pending, pending.correct_answer)
        return _AnswerContext(
            user=user,
            session=session,
            pending=pending,
            selected_option_id=selected_option_id,
            correct_answer_text=correct_answer_text,
        )

    @staticmethod
    def _pending_answer_payload(session: Any) -> QuizQuestionPayload:
        metadata = session.api_metadata or {}
        pending_raw = metadata.get("pending_question")
        if not isinstance(pending_raw, dict):
            raise QuestionStateError("No active question in session")
        return deserialize_question_payload(pending_raw)

    async def _duplicate_result(
        self,
        db: AsyncSession,
        context: _AnswerContext,
        telegram_update_id: int | None,
    ) -> AnswerResult | None:
        existing_by_update = await self._service._get_answer_by_update_id(db, telegram_update_id)
        if existing_by_update is not None:
            if existing_by_update.user_id != context.user.id or existing_by_update.session_id != context.session.id:
                raise QuestionStateError("Telegram update id does not belong to this session")
            return await self._build_duplicate_result(db, context, existing_by_update)

        existing = await self._service._answer_repo.get_by_session_and_question(
            db,
            session_id=context.session.id,
            user_id=context.user.id,
            external_quiz_id=context.pending.question_id,
        )
        if existing is None:
            return None
        return await self._build_duplicate_result(db, context, existing)

    async def _create_answer_or_duplicate(
        self,
        db: AsyncSession,
        context: _AnswerContext,
        *,
        is_correct: bool,
        telegram_update_id: int | None,
    ) -> Any:
        try:
            answer = await self._create_answer(
                db,
                context,
                is_correct=is_correct,
                telegram_update_id=telegram_update_id,
            )
            await self._mark_session_item_answered(db, context)
            await db.flush()
            return answer
        except IntegrityError as exc:
            return await self._duplicate_after_integrity_error(db, context, telegram_update_id, exc)

    async def _create_answer(
        self,
        db: AsyncSession,
        context: _AnswerContext,
        *,
        is_correct: bool,
        telegram_update_id: int | None,
    ) -> Any:
        service = self._service
        return await service._answer_repo.create(
            db,
            session_id=context.session.id,
            user_id=context.user.id,
            external_quiz_id=context.pending.question_id,
            selected_answer=context.selected_option_id,
            correct_answer=context.pending.correct_answer,
            is_correct=is_correct,
            training_session_item_id=context.pending.training_session_item_id,
            question_reference_id=context.pending.question_reference_id,
            quiz_source=service.QUIZ_SOURCE,
            level=context.pending.level,
            theme=context.pending.theme,
            theme_key=context.pending.theme_key,
            session_type=service._session_flow(context.session),
            metadata_snapshot=context.pending.metadata_snapshot,
            telegram_update_id=telegram_update_id,
        )

    async def _mark_session_item_answered(self, db: AsyncSession, context: _AnswerContext) -> None:
        service = self._service
        if hasattr(service._session_repo, "increment_answered_count"):
            await service._session_repo.increment_answered_count(db, context.session, 1)
        session_item = await service._session_item_repo.get_by_session_item(
            db,
            session_id=context.session.id,
            item_id=context.pending.question_id,
        )
        if session_item is not None:
            await service._session_item_repo.mark_answered(db, session_item)

    async def _duplicate_after_integrity_error(
        self,
        db: AsyncSession,
        context: _AnswerContext,
        telegram_update_id: int | None,
        integrity_error: IntegrityError,
    ) -> AnswerResult:
        service = self._service
        await db.rollback()
        existing = await service._get_answer_by_update_id(db, telegram_update_id)
        if existing is None:
            existing = await service._answer_repo.get_by_session_and_question(
                db,
                session_id=context.session.id,
                user_id=context.user.id,
                external_quiz_id=context.pending.question_id,
            )
        if existing is None:
            raise integrity_error
        if existing.user_id != context.user.id or existing.session_id != context.session.id:
            raise QuestionStateError("Duplicate answer belongs to another session")
        return await self._build_duplicate_result(db, context, existing)

    async def _build_duplicate_result(
        self,
        db: AsyncSession,
        context: _AnswerContext,
        existing: Any,
    ) -> AnswerResult:
        total_answers = await self._service._answer_repo.count_by_session(db, context.session.id)
        return AnswerResult(
            selected_answer=context.selected_option_id,
            correct_answer=context.pending.correct_answer,
            question_token=context.pending.question_token,
            is_correct=existing.is_correct,
            is_duplicate=True,
            is_completed=total_answers >= context.session.total_questions,
            explanation=context.pending.explanation,
            correct_answers=context.session.correct_answers,
            total_questions=context.session.total_questions,
            session_id=context.session.id,
            correct_answer_text=context.correct_answer_text,
        )

    async def _apply_session_counters(
        self,
        db: AsyncSession,
        context: _AnswerContext,
        *,
        is_correct: bool,
    ) -> None:
        if is_correct:
            await self._service._session_repo.increment_correct_answers(db, context.session, 1)

    async def _record_learning_side_effects(
        self,
        db: AsyncSession,
        context: _AnswerContext,
        *,
        answer: Any,
        is_correct: bool,
    ) -> int:
        mistake_count = await self._record_mistake_side_effects(
            db,
            context,
            answer=answer,
            is_correct=is_correct,
        )
        await self._record_progress_side_effect(db, context, answer=answer, is_correct=is_correct)
        return mistake_count

    async def _record_mistake_side_effects(
        self,
        db: AsyncSession,
        context: _AnswerContext,
        *,
        answer: Any,
        is_correct: bool,
    ) -> int:
        service = self._service
        if service._mistakes_service is None:
            return 0
        if is_correct and service._is_review_session(context.session):
            await self._record_review_success(db, context, answer)
            return 0
        if is_correct:
            return 0
        return await self._record_wrong_answer(db, context, answer)

    async def _record_review_success(self, db: AsyncSession, context: _AnswerContext, answer: Any) -> None:
        await self._service._mistakes_service.record_review_success(
            db,
            context.user.telegram_user_id,
            external_quiz_id=context.pending.question_id,
            question_level=context.pending.level,
            question_theme=context.pending.theme,
            correct_answer=context.pending.correct_answer,
            session_id=context.session.id,
            user_answer_id=getattr(answer, "id", None),
            metadata_snapshot=context.pending.metadata_snapshot,
        )

    async def _record_wrong_answer(self, db: AsyncSession, context: _AnswerContext, answer: Any) -> int:
        service = self._service
        mistake = await service._mistakes_service.record_wrong_answer(
            db,
            context.user.telegram_user_id,
            external_quiz_id=context.pending.question_id,
            level=context.pending.level,
            theme=context.pending.theme,
            wrong_answer=context.selected_option_id,
            correct_answer=context.pending.correct_answer,
            source_snapshot={
                "session_type": service._session_flow(context.session),
                "question_token": context.pending.question_token,
                "metadata_snapshot": context.pending.metadata_snapshot,
            },
            session_id=context.session.id,
            user_answer_id=getattr(answer, "id", None),
            metadata_snapshot=context.pending.metadata_snapshot,
        )
        if mistake is not None and int(getattr(mistake, "mistake_count", 0) or 0) == 1:
            return 1
        return 0

    async def _record_progress_side_effect(
        self,
        db: AsyncSession,
        context: _AnswerContext,
        *,
        answer: Any,
        is_correct: bool,
    ) -> None:
        service = self._service
        if service._progress_service is None:
            return
        await service._progress_service.record_answer_result(
            db,
            context.user.telegram_user_id,
            level=context.pending.level,
            theme=context.pending.theme,
            is_correct=is_correct,
            is_duplicate=False,
            session_id=context.session.id,
            user_answer_id=getattr(answer, "id", None),
            item_id=context.pending.question_id,
            theme_key=context.pending.theme_key,
            available_items_count=_available_count_from_metadata(context.pending.metadata_snapshot),
            metadata_snapshot=context.pending.metadata_snapshot,
            reason_code="answer_accepted",
        )

    async def _record_question_answered(
        self,
        db: AsyncSession,
        context: _AnswerContext,
        *,
        is_correct: bool,
    ) -> None:
        service = self._service
        await service._record_analytics(
            db,
            event_name="question_answered",
            user_id=context.user.id,
            session_id=context.session.id,
            event_metadata={
                "session_type": service._session_flow(context.session),
                "level": context.pending.level,
                "theme": context.pending.theme,
                "item_id": context.pending.question_id,
                "is_correct": is_correct,
                "position": context.pending.position,
            },
        )

    async def _complete_and_build_result(
        self,
        db: AsyncSession,
        context: _AnswerContext,
        *,
        is_correct: bool,
        new_mistakes_count: int,
    ) -> AnswerResult:
        total_answers = await self._service._answer_repo.count_by_session(db, context.session.id)
        completed = total_answers >= context.session.total_questions
        weak_theme = None
        recommendation_text = None
        if completed:
            weak_theme, recommendation_text = await self._complete_session(
                db,
                context,
                total_answers=total_answers,
                new_mistakes_count=new_mistakes_count,
            )
        await db.flush()
        return AnswerResult(
            selected_answer=context.selected_option_id,
            correct_answer=context.pending.correct_answer,
            question_token=context.pending.question_token,
            is_correct=is_correct,
            is_duplicate=False,
            is_completed=completed,
            explanation=context.pending.explanation,
            correct_answers=context.session.correct_answers,
            total_questions=context.session.total_questions,
            session_id=context.session.id,
            correct_answer_text=context.correct_answer_text,
            weak_theme=weak_theme,
            new_mistakes_count=new_mistakes_count,
            recommendation_text=recommendation_text,
        )

    async def _complete_session(
        self,
        db: AsyncSession,
        context: _AnswerContext,
        *,
        total_answers: int,
        new_mistakes_count: int,
    ) -> tuple[str | None, str]:
        service = self._service
        await service._session_repo.mark_completed(db, context.session)
        await service._session_repo.clear_pending_question(db, context.session)
        weak_theme, recommendation_text = await service._completion_context(
            db,
            context.user.telegram_user_id,
            new_mistakes_count=new_mistakes_count,
        )
        completion_metadata = {
            "session_type": service._session_flow(context.session),
            "level": context.session.level,
            "theme": context.session.theme,
            "answered_count": total_answers,
            "correct_answers": context.session.correct_answers,
            "planned_question_count": context.session.total_questions,
        }
        await service._record_analytics(
            db,
            event_name="training_completed",
            user_id=context.user.id,
            session_id=context.session.id,
            event_metadata=completion_metadata,
        )
        await service._record_analytics(
            db,
            event_name="result_shown",
            user_id=context.user.id,
            session_id=context.session.id,
            event_metadata=completion_metadata,
        )
        return weak_theme, recommendation_text


def _available_count_from_metadata(metadata_snapshot: dict[str, object] | None) -> int | None:
    if metadata_snapshot is None:
        return None
    value = metadata_snapshot.get("available_items_count")
    if isinstance(value, int) and value >= 0:
        return value
    return None
