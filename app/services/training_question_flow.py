from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.quiz_bank import QuizBankRequestContext
from app.quiz_bank.errors import QuizBankError
from app.services.entitlements import FEATURE_MISTAKE_REPEAT
from app.services.training_payloads import (
    ActiveSessionNotFoundError,
    NoMoreQuestionsError,
    NoReviewItemsError,
    QuizQuestionPayload,
    answer_text,
    build_question_payload,
    deserialize_question_payload,
    normalize_explanation,
    normalize_text,
    question_metadata_snapshot,
    serialize_question_payload,
)


@dataclass(frozen=True)
class _QuestionContext:
    user: Any
    session: Any
    answered: int


@dataclass(frozen=True)
class _QuestionRequest:
    request_context: QuizBankRequestContext
    is_review_session: bool
    mistake_item_ids: list[str]


class TrainingQuestionProcessor:
    """Prepare and persist current training questions."""

    def __init__(self, service: Any) -> None:
        self._service = service

    async def get_or_create_current_question(
        self,
        db: AsyncSession,
        telegram_user_id: int,
        *,
        force_refresh: bool,
    ) -> QuizQuestionPayload:
        context = await self._load_active_question_context(db, telegram_user_id)
        if not force_refresh:
            pending = self._pending_payload(context.session)
            if pending is not None:
                return pending

        seen_item_ids = await self._service._answer_repo.list_question_ids_by_session(db, context.session.id)
        question_request = await self._build_question_request(
            db,
            context.user,
            context.session,
            seen_item_ids,
        )
        await self._ensure_daily_question_available(db, context.user, context.session)
        response = await self._request_quiz(db, context, question_request)
        question = await self._first_response_item(db, context, question_request, response)
        return await self._persist_question(db, context, response, question)

    async def _load_active_question_context(
        self,
        db: AsyncSession,
        telegram_user_id: int,
    ) -> _QuestionContext:
        service = self._service
        user = await service.get_user(db, telegram_user_id)
        session = await service._session_repo.get_active_for_user(db, user.id)
        if session is None:
            raise ActiveSessionNotFoundError("No active session")
        if session.status != service.ACTIVE_SESSION_STATUS:
            raise ActiveSessionNotFoundError("Session is not active")

        answered = await service._answer_repo.count_by_session(db, session.id)
        if answered >= session.total_questions:
            await service._session_repo.mark_completed(db, session)
            await service._session_repo.clear_pending_question(db, session)
            await db.flush()
            raise ActiveSessionNotFoundError("Session already completed")
        return _QuestionContext(user=user, session=session, answered=answered)

    @staticmethod
    def _pending_payload(session: Any) -> QuizQuestionPayload | None:
        metadata = session.api_metadata or {}
        pending = metadata.get("pending_question")
        if not isinstance(pending, dict):
            return None

        payload = deserialize_question_payload(pending)
        if payload.session_id != session.id:
            return None
        if payload.total_questions != session.total_questions:
            return None
        return payload

    async def _build_question_request(
        self,
        db: AsyncSession,
        user: Any,
        session: Any,
        seen_item_ids: list[str],
    ) -> _QuestionRequest:
        service = self._service
        is_review_session = service._is_review_session(session)
        mistake_item_ids: list[str] = []
        if is_review_session and service._mistakes_service is not None:
            mistake_item_ids = await self._review_item_ids(db, user, session)
            await self._ensure_review_entitlement(db, user, session)

        return _QuestionRequest(
            request_context=QuizBankRequestContext(
                seen_item_ids=seen_item_ids,
                target_level=session.level,
                session_type=service._session_flow(session),
                mistake_item_ids=mistake_item_ids or None,
            ),
            is_review_session=is_review_session,
            mistake_item_ids=mistake_item_ids,
        )

    async def _review_item_ids(self, db: AsyncSession, user: Any, session: Any) -> list[str]:
        service = self._service
        review_items = await service._mistakes_service.get_review_items(db, user.telegram_user_id)
        item_ids = [entry.external_quiz_id for entry in review_items]
        if item_ids:
            return item_ids

        await service._session_repo.mark_failed(db, session)
        await service._session_repo.clear_pending_question(db, session)
        await db.flush()
        raise NoReviewItemsError("No active mistakes to review")

    async def _ensure_review_entitlement(self, db: AsyncSession, user: Any, session: Any) -> None:
        service = self._service
        if service._entitlement_service is None:
            return
        await service._entitlement_service.ensure_entitlement(
            db,
            user.telegram_user_id,
            feature=FEATURE_MISTAKE_REPEAT,
        )

    async def _ensure_daily_question_available(self, db: AsyncSession, user: Any, session: Any) -> None:
        service = self._service
        if service._entitlement_service is None:
            return
        await service._entitlement_service.ensure_daily_question_available(
            db,
            user.telegram_user_id,
            session_id=session.id,
            level=session.level,
            theme=session.theme,
        )

    async def _request_quiz(
        self,
        db: AsyncSession,
        context: _QuestionContext,
        question_request: _QuestionRequest,
    ):
        service = self._service
        try:
            return await service._quiz_bank_service.request_quiz(
                level=context.session.level,
                theme=context.session.theme,
                limit=1,
                user_context=question_request.request_context,
            )
        except QuizBankError as exc:
            await service._record_quiz_bank_error(
                db,
                exc,
                user_id=context.user.id,
                session_id=context.session.id,
                level=context.session.level,
                theme=context.session.theme,
            )
            raise

    async def _first_response_item(
        self,
        db: AsyncSession,
        context: _QuestionContext,
        question_request: _QuestionRequest,
        response: Any,
    ) -> Any:
        if response.returned_count >= 1 and response.items:
            return response.items[0]

        await self._mark_no_more_questions(db, context, question_request)
        raise NoMoreQuestionsError("Quiz Bank returned no questions")

    async def _mark_no_more_questions(
        self,
        db: AsyncSession,
        context: _QuestionContext,
        question_request: _QuestionRequest,
    ) -> None:
        service = self._service
        if (
            question_request.is_review_session
            and service._mistakes_service is not None
            and question_request.mistake_item_ids
        ):
            await service._mistakes_service.mark_review_items_unavailable(
                db,
                context.user.telegram_user_id,
                external_quiz_ids=question_request.mistake_item_ids,
                session_id=context.session.id,
            )
        await service._session_repo.mark_failed(db, context.session)
        await service._session_repo.clear_pending_question(db, context.session)
        await db.flush()

    async def _persist_question(
        self,
        db: AsyncSession,
        context: _QuestionContext,
        response: Any,
        question: Any,
    ) -> QuizQuestionPayload:
        metadata_snapshot = await self._question_metadata_snapshot(db, context, question)
        question_reference = await self._upsert_question_reference(db, question, metadata_snapshot)
        await db.flush()

        session_item = await self._create_shown_session_item(db, context, question, question_reference)
        await db.flush()
        payload = build_question_payload(
            session_id=context.session.id,
            question=question,
            position=context.answered + 1,
            total_questions=context.session.total_questions,
            question_reference_id=question_reference.id,
            training_session_item_id=session_item.id,
            metadata_snapshot=metadata_snapshot,
        )
        await self._save_pending_question(db, context.session, payload, response)
        await db.flush()
        return payload

    async def _question_metadata_snapshot(
        self,
        db: AsyncSession,
        context: _QuestionContext,
        question: Any,
    ) -> dict[str, Any]:
        metadata_snapshot = question_metadata_snapshot(question)
        available_items_count = await self._service._available_items_count_for_question(
            db,
            user_id=context.user.id,
            session_id=context.session.id,
            level=question.level,
            theme=question.theme,
        )
        if available_items_count is not None:
            metadata_snapshot["available_items_count"] = available_items_count
        return metadata_snapshot

    async def _upsert_question_reference(
        self,
        db: AsyncSession,
        question: Any,
        metadata_snapshot: dict[str, Any],
    ) -> Any:
        return await self._service._question_reference_repo.upsert_snapshot(
            db,
            item_id=question.item_id,
            level=question.level,
            theme=question.theme,
            theme_key=question.theme_key,
            metadata_snapshot=metadata_snapshot,
            content_version=question.content_version,
            question_text_snapshot=normalize_text(question.question_text),
            correct_answer_snapshot=answer_text(question, question.correct_answer.option_id),
            explanation_snapshot=normalize_explanation(question.explanation),
        )

    async def _create_shown_session_item(
        self,
        db: AsyncSession,
        context: _QuestionContext,
        question: Any,
        question_reference: Any,
    ) -> Any:
        service = self._service
        existing_session_item = await service._session_item_repo.get_by_session_item(
            db,
            session_id=context.session.id,
            item_id=question.item_id,
        )
        session_item = await service._session_item_repo.create_shown(
            db,
            session_id=context.session.id,
            user_id=context.user.id,
            question_reference_id=question_reference.id,
            item_id=question.item_id,
            position=context.answered + 1,
        )
        await self._record_question_shown(db, context, session_item, existing_session_item)
        return session_item

    async def _record_question_shown(
        self,
        db: AsyncSession,
        context: _QuestionContext,
        session_item: Any,
        existing_session_item: Any,
    ) -> None:
        service = self._service
        if hasattr(service._session_repo, "increment_shown_questions_count") and existing_session_item is None:
            await service._session_repo.increment_shown_questions_count(db, context.session, 1)
        if existing_session_item is None and service._entitlement_service is not None:
            limit_state = await service._entitlement_service.charge_daily_question(
                db,
                context.user.telegram_user_id,
            )
            if hasattr(service._session_item_repo, "mark_daily_limit_charged"):
                await service._session_item_repo.mark_daily_limit_charged(
                    db,
                    session_item,
                    daily_limit_id=limit_state.daily_limit.id,
                )
        elif hasattr(service._session_item_repo, "mark_daily_limit_charged"):
            await service._session_item_repo.mark_daily_limit_charged(db, session_item)

    async def _save_pending_question(
        self,
        db: AsyncSession,
        session: Any,
        payload: QuizQuestionPayload,
        response: Any,
    ) -> None:
        service = self._service
        await service._session_repo.set_pending_question(db, session, serialize_question_payload(payload))
        api_metadata = dict(session.api_metadata or {})
        api_metadata["requested_count"] = response.requested_count
        api_metadata["returned_count"] = response.returned_count
        api_metadata["has_more"] = response.has_more
        await service._session_repo.set_api_metadata(db, session, api_metadata)
