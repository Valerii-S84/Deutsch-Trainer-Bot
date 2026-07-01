from __future__ import annotations

from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.answers import AnswerWriteResult
from app.runtime.idempotency_locks import answer_attempt_lock
from app.runtime.timing import timing_span
from app.services.training_answer_persistence import create_answer_or_duplicate
from app.services.training_answer_state import AnswerContext, AnswerSnapshot
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
        async with answer_attempt_lock(f"{session_id}:{question_token}"):
            return await self._submit_answer_locked(
                db,
                telegram_user_id,
                session_id,
                question_token,
                selected_option_id,
                telegram_update_id,
            )

    async def _submit_answer_locked(
        self,
        db: AsyncSession,
        telegram_user_id: int,
        session_id: int,
        question_token: str,
        selected_option_id: str,
        telegram_update_id: int | None,
    ) -> AnswerResult:
        with timing_span("answer.total_request_ms"):
            context, snapshot = await self._validated_context_and_snapshot(
                db,
                telegram_user_id,
                session_id,
                question_token,
                selected_option_id,
            )
            is_correct = selected_option_id == snapshot.pending.correct_answer
            duplicate = await self._prechecked_duplicate(db, snapshot, telegram_update_id)
            if duplicate is not None:
                return duplicate

            answer = await create_answer_or_duplicate(
                self,
                db,
                context,
                snapshot,
                is_correct=is_correct,
                telegram_update_id=telegram_update_id,
            )
            if isinstance(answer, AnswerResult):
                return answer
            return await self._apply_side_effects_and_result(db, context, snapshot, answer, is_correct=is_correct)

    async def _validated_context_and_snapshot(
        self,
        db: AsyncSession,
        telegram_user_id: int,
        session_id: int,
        question_token: str,
        selected_option_id: str,
    ) -> tuple[AnswerContext, AnswerSnapshot]:
        with timing_span("answer.validate_ms"):
            context = await self._validate_pending_answer(
                db,
                telegram_user_id,
                session_id,
                question_token,
                selected_option_id,
            )
            return context, self._snapshot(context)

    async def _prechecked_duplicate(
        self,
        db: AsyncSession,
        snapshot: AnswerSnapshot,
        telegram_update_id: int | None,
    ) -> AnswerResult | None:
        if hasattr(self._service._answer_repo, "create_idempotent"):
            return None
        return await self._duplicate_result(db, snapshot, telegram_update_id)

    async def _apply_side_effects_and_result(
        self,
        db: AsyncSession,
        context: AnswerContext,
        snapshot: AnswerSnapshot,
        answer: Any,
        *,
        is_correct: bool,
    ) -> AnswerResult:
        with timing_span("answer.session_update_ms"):
            await self._apply_session_counters(db, context, is_correct=is_correct)
        with timing_span("answer.response_formatting_ms"):
            result = await self._complete_and_build_result(
                db,
                context,
                snapshot,
                is_correct=is_correct,
                new_mistakes_count=0,
            )
        with timing_span("answer.outbox_insert_ms"):
            await self._enqueue_answer_accepted(db, snapshot, answer=answer, is_correct=is_correct, result=result)
        return result

    async def _validate_pending_answer(
        self,
        db: AsyncSession,
        telegram_user_id: int,
        session_id: int,
        question_token: str,
        selected_option_id: str,
    ) -> AnswerContext:
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
        return AnswerContext(
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
        snapshot: AnswerSnapshot,
        telegram_update_id: int | None,
    ) -> AnswerResult | None:
        existing_by_update = await self._service._get_answer_by_update_id(db, telegram_update_id)
        if existing_by_update is not None:
            if existing_by_update.user_id != snapshot.user_id or existing_by_update.session_id != snapshot.session_id:
                raise QuestionStateError("Telegram update id does not belong to this session")
            return await self._build_duplicate_result(db, snapshot, _answer_record(existing_by_update))
        existing = await self._service._answer_repo.get_by_session_and_question(
            db,
            session_id=snapshot.session_id,
            user_id=snapshot.user_id,
            external_quiz_id=snapshot.pending.question_id,
        )
        if existing is None:
            return None
        return await self._build_duplicate_result(db, snapshot, _answer_record(existing))

    async def _mark_session_item_answered(self, db: AsyncSession, context: AnswerContext) -> None:
        service = self._service
        if hasattr(service._session_repo, "increment_answered_count"):
            await service._session_repo.increment_answered_count(db, context.session, 1)
        if hasattr(service._session_item_repo, "mark_answered_by_session_item"):
            await service._session_item_repo.mark_answered_by_session_item(
                db,
                session_id=context.session.id,
                item_id=context.pending.question_id,
            )
            return
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
        snapshot: AnswerSnapshot,
        telegram_update_id: int | None,
        integrity_error: IntegrityError,
        *,
        rollback: bool = True,
    ) -> AnswerResult:
        service = self._service
        if rollback:
            await db.rollback()
        existing = await service._get_answer_by_update_id(db, telegram_update_id)
        if existing is None:
            existing = await service._answer_repo.get_by_session_and_question(
                db,
                session_id=snapshot.session_id,
                user_id=snapshot.user_id,
                external_quiz_id=snapshot.pending.question_id,
            )
        if existing is None:
            raise integrity_error
        if existing.user_id != snapshot.user_id or existing.session_id != snapshot.session_id:
            raise QuestionStateError("Duplicate answer belongs to another session")
        return await self._build_duplicate_result(db, snapshot, _answer_record(existing))

    async def _build_duplicate_result(
        self,
        db: AsyncSession,
        snapshot: AnswerSnapshot,
        existing: AnswerWriteResult,
    ) -> AnswerResult:
        total_answers = await self._service._answer_repo.count_by_session(db, snapshot.session_id)
        return AnswerResult(
            selected_answer=snapshot.selected_option_id,
            correct_answer=snapshot.pending.correct_answer,
            question_token=snapshot.pending.question_token,
            is_correct=existing.is_correct,
            is_duplicate=True,
            is_completed=total_answers >= snapshot.total_questions,
            explanation=snapshot.pending.explanation,
            correct_answers=snapshot.correct_answers,
            total_questions=snapshot.total_questions,
            session_id=snapshot.session_id,
            correct_answer_text=snapshot.correct_answer_text,
        )

    async def _apply_session_counters(
        self,
        db: AsyncSession,
        context: AnswerContext,
        *,
        is_correct: bool,
    ) -> None:
        if is_correct:
            await self._service._session_repo.increment_correct_answers(db, context.session, 1)

    async def _enqueue_answer_accepted(
        self,
        db: AsyncSession,
        snapshot: AnswerSnapshot,
        *,
        answer: Any,
        is_correct: bool,
        result: AnswerResult,
    ) -> None:
        answer_id = getattr(answer, "id", None)
        if not isinstance(answer_id, int):
            await db.flush()
            answer_id = getattr(answer, "id", None)
        if not isinstance(answer_id, int):
            raise QuestionStateError("Accepted answer id is unavailable")
        await self._service._outbox_repo.enqueue(
            db,
            event_type=ANSWER_ACCEPTED_EVENT,
            aggregate_type="user_answer",
            aggregate_id=answer_id,
            idempotency_key=f"{ANSWER_ACCEPTED_EVENT}:{answer_id}",
            payload=self._answer_accepted_payload(
                snapshot,
                answer_id=answer_id,
                is_correct=is_correct,
                result=result,
            ),
        )

    def _answer_accepted_payload(
        self,
        snapshot: AnswerSnapshot,
        *,
        answer_id: int,
        is_correct: bool,
        result: AnswerResult,
    ) -> dict[str, object]:
        payload: dict[str, object] = {
            "answer_id": answer_id,
            "telegram_user_id": snapshot.telegram_user_id,
            "user_id": snapshot.user_id,
            "session_id": snapshot.session_id,
            "question_token": snapshot.pending.question_token,
            "item_id": snapshot.pending.question_id,
            "level": snapshot.pending.level,
            "theme": snapshot.pending.theme,
            "theme_key": snapshot.pending.theme_key,
            "selected_answer": snapshot.selected_option_id,
            "correct_answer": snapshot.pending.correct_answer,
            "is_correct": is_correct,
            "session_type": snapshot.session_type,
            "position": snapshot.pending.position,
            "available_items_count": _available_count_from_metadata(snapshot.pending.metadata_snapshot),
            "metadata_snapshot": snapshot.pending.metadata_snapshot,
            "session_completed": result.is_completed,
            "answered_count": result.total_questions if result.is_completed else snapshot.answered_count + 1,
            "correct_answers": result.correct_answers,
            "total_questions": result.total_questions,
        }
        return payload

    async def _complete_and_build_result(
        self,
        db: AsyncSession,
        context: AnswerContext,
        snapshot: AnswerSnapshot,
        *,
        is_correct: bool,
        new_mistakes_count: int,
    ) -> AnswerResult:
        total_answers = _answered_count(context.session)
        if total_answers <= 0:
            total_answers = await self._service._answer_repo.count_by_session(db, snapshot.session_id)
        completed = total_answers >= snapshot.total_questions
        weak_theme = None
        recommendation_text = None
        if completed:
            weak_theme, recommendation_text = await self._complete_session(
                db,
                context,
            )
        await db.flush()
        return AnswerResult(
            selected_answer=context.selected_option_id,
            correct_answer=context.pending.correct_answer,
            question_token=context.pending.question_token,
            is_correct=is_correct,
            is_duplicate=False,
            is_completed=completed,
            explanation=snapshot.pending.explanation,
            correct_answers=int(getattr(context.session, "correct_answers", snapshot.correct_answers) or 0),
            total_questions=snapshot.total_questions,
            session_id=snapshot.session_id,
            correct_answer_text=snapshot.correct_answer_text,
            weak_theme=weak_theme,
            new_mistakes_count=new_mistakes_count,
            recommendation_text=recommendation_text,
        )

    async def _complete_session(
        self,
        db: AsyncSession,
        context: AnswerContext,
    ) -> tuple[str | None, str]:
        service = self._service
        await service._session_repo.mark_completed(db, context.session)
        await service._session_repo.clear_pending_question(db, context.session)
        return None, "Starte eine neue Runde, um weiter zu üben."

    def _snapshot(self, context: AnswerContext) -> AnswerSnapshot:
        return AnswerSnapshot(
            telegram_user_id=int(context.user.telegram_user_id),
            user_id=int(context.user.id),
            session_id=int(context.session.id),
            session_status=str(context.session.status),
            session_type=self._service._session_flow(context.session),
            level=str(context.session.level),
            theme=context.session.theme,
            total_questions=int(context.session.total_questions),
            correct_answers=int(context.session.correct_answers or 0),
            answered_count=_answered_count(context.session),
            pending=context.pending,
            selected_option_id=context.selected_option_id,
            correct_answer_text=context.correct_answer_text,
        )


def _available_count_from_metadata(metadata_snapshot: dict[str, object] | None) -> int | None:
    if metadata_snapshot is None:
        return None
    value = metadata_snapshot.get("available_items_count")
    if isinstance(value, int) and value >= 0:
        return value
    return None


def _answered_count(session: Any) -> int:
    value = getattr(session, "answered_count", None)
    if isinstance(value, int) and value >= 0:
        return value
    return 0


def _answer_record(answer: Any) -> AnswerWriteResult:
    return AnswerWriteResult(
        id=int(answer.id),
        session_id=int(answer.session_id),
        user_id=int(answer.user_id),
        external_quiz_id=str(answer.external_quiz_id),
        selected_answer=str(answer.selected_answer),
        correct_answer=str(answer.correct_answer),
        is_correct=bool(answer.is_correct),
        created=False,
    )
