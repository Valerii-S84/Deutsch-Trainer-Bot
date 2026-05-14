from __future__ import annotations

from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.quiz_bank import QuizBankRequestContext, QuizBankService
from app.services.entitlements import EntitlementService, FEATURE_MISTAKE_REPEAT
from app.services.progress import ProgressService
from app.services.mistakes import MistakeService
from app.services.training_session_lifecycle import TrainingSessionLifecycleMixin
from app.services.training_payloads import (
    ActiveSessionConflictError,
    ActiveSessionNotFoundError,
    AnswerResult,
    NoMoreQuestionsError,
    NoReviewItemsError,
    QuestionStateError,
    QuizQuestionPayload,
    answer_text,
    build_question_payload,
    deserialize_question_payload,
    normalize_explanation,
    normalize_text,
    option_ids,
    option_text,
    question_metadata_snapshot,
    serialize_question_payload,
)
from app.repositories.answers import AnswerRepository
from app.repositories.analytics_events import AnalyticsEventRepository
from app.repositories.question_references import QuestionReferenceRepository
from app.repositories.quiz_sessions import QuizSessionRepository, QuizSessionStatus
from app.repositories.training_session_items import TrainingSessionItemRepository
from app.repositories.users import UserRepository


class TrainingSessionService(TrainingSessionLifecycleMixin):
    """Runtime session orchestration with learning-state side effects."""

    ACTIVE_SESSION_STATUS = QuizSessionStatus.active
    COMPLETED_SESSION_STATUS = QuizSessionStatus.completed
    CANCELLED_SESSION_STATUS = QuizSessionStatus.cancelled
    FAILED_SESSION_STATUS = QuizSessionStatus.failed
    DEFAULT_SESSION_QUESTIONS = 5
    QUIZ_SOURCE = "quiz_bank_api"
    SESSION_FLOW_REGULAR = "regular"
    SESSION_FLOW_REVIEW = "mistake_review"
    SESSION_FLOW_RECOMMENDED = "recommended"

    def __init__(
        self,
        *,
        user_repo: UserRepository | None = None,
        session_repo: QuizSessionRepository | None = None,
        answer_repo: AnswerRepository | None = None,
        analytics_repo: AnalyticsEventRepository | None = None,
        question_reference_repo: QuestionReferenceRepository | None = None,
        session_item_repo: TrainingSessionItemRepository | None = None,
        quiz_service: QuizBankService | None = None,
        progress_service: ProgressService | None = None,
        mistakes_service: MistakeService | None = None,
        entitlement_service: EntitlementService | None = None,
    ) -> None:
        self._user_repo = user_repo or UserRepository()
        self._session_repo = session_repo or QuizSessionRepository()
        self._answer_repo = answer_repo or AnswerRepository()
        self._analytics_repo = analytics_repo or AnalyticsEventRepository()
        self._question_reference_repo = question_reference_repo or QuestionReferenceRepository()
        self._session_item_repo = session_item_repo or TrainingSessionItemRepository()
        self._quiz_service = quiz_service
        self._progress_service = progress_service
        self._mistakes_service = mistakes_service
        self._entitlement_service = entitlement_service

    @property
    def _quiz_bank_service(self) -> QuizBankService:
        if self._quiz_service is None:
            self._quiz_service = QuizBankService()
        return self._quiz_service

    def _session_flow(self, session) -> str:
        metadata = session.source_metadata or {}
        return str(metadata.get("flow") or self.SESSION_FLOW_REGULAR)

    def _is_review_session(self, session) -> bool:
        return self._session_flow(session) == self.SESSION_FLOW_REVIEW

    def _default_source_metadata(self, flow: str, telegram_user_id: int) -> dict[str, str]:
        return {
            "flow": flow,
            "created_by": str(telegram_user_id),
        }

    async def _record_analytics(
        self,
        db: AsyncSession,
        *,
        event_name: str,
        user_id: int | None,
        session_id: int | None,
        event_metadata: dict[str, Any] | None = None,
    ) -> None:
        await self._analytics_repo.record(
            db,
            event_name=event_name,
            user_id=user_id,
            session_id=session_id,
            event_metadata=event_metadata,
            source="training",
        )

    async def _completion_context(
        self,
        db: AsyncSession,
        telegram_user_id: int,
        *,
        new_mistakes_count: int,
    ) -> tuple[str | None, str]:
        weak_theme = None
        if self._mistakes_service is not None:
            weak_areas = await self._mistakes_service.get_weak_areas(db, telegram_user_id)
            if weak_areas:
                weak_theme = str(weak_areas[0].get("theme") or "")
        if weak_theme:
            return weak_theme, f"Wiederhole deine Fehler in {weak_theme}."
        if new_mistakes_count:
            return None, "Wiederhole deine neuen Fehler, bevor du weitergehst."
        return None, "Starte eine neue Runde, um weiter zu üben."

    @staticmethod
    def _session_question_limit(requested_total_questions: int, review_items: list[object] | None = None) -> int:
        requested = max(1, requested_total_questions)
        if review_items is None or not review_items:
            return requested
        return max(1, min(requested, len(review_items)))

    async def get_user(self, db: AsyncSession, telegram_user_id: int):
        return await self._user_repo.create_if_missing(db, telegram_user_id)

    async def set_user_preferences(
        self,
        db: AsyncSession,
        telegram_user_id: int,
        *,
        level: str | None = None,
        theme: str | None = None,
    ) -> None:
        await self._user_repo.set_training_preferences(db, telegram_user_id, level=level, theme=theme)

    async def get_or_create_current_question(
        self,
        db: AsyncSession,
        telegram_user_id: int,
        *,
        force_refresh: bool,
    ) -> QuizQuestionPayload:
        user = await self.get_user(db, telegram_user_id)
        session = await self._session_repo.get_active_for_user(db, user.id)
        if session is None:
            raise ActiveSessionNotFoundError("No active session")
        if session.status != self.ACTIVE_SESSION_STATUS:
            raise ActiveSessionNotFoundError("Session is not active")

        answered = await self._answer_repo.count_by_session(db, session.id)
        if answered >= session.total_questions:
            await self._session_repo.mark_completed(db, session)
            await self._session_repo.clear_pending_question(db, session)
            await db.flush()
            raise ActiveSessionNotFoundError("Session already completed")

        metadata = session.api_metadata or {}
        if not force_refresh:
            pending = metadata.get("pending_question")
            if isinstance(pending, dict):
                payload = deserialize_question_payload(pending)
                if payload.session_id == session.id and payload.total_questions == session.total_questions:
                    return payload

        seen_item_ids = await self._answer_repo.list_question_ids_by_session(db, session.id)
        is_review_session = self._is_review_session(session)
        mistake_item_ids: list[str] = []
        if is_review_session and self._mistakes_service is not None:
            review_items = await self._mistakes_service.get_review_items(db, user.telegram_user_id)
            mistake_item_ids = [entry.external_quiz_id for entry in review_items]
            if not mistake_item_ids:
                await self._session_repo.mark_failed(db, session)
                await self._session_repo.clear_pending_question(db, session)
                await db.flush()
                raise NoReviewItemsError("No active mistakes to review")

        if is_review_session and self._mistakes_service is not None:
            if self._entitlement_service is not None:
                await self._entitlement_service.ensure_entitlement(
                    db,
                    user.telegram_user_id,
                    feature=FEATURE_MISTAKE_REPEAT,
                )
            request_context = QuizBankRequestContext(
                seen_item_ids=seen_item_ids,
                target_level=session.level,
                session_type=self._session_flow(session),
                mistake_item_ids=mistake_item_ids,
            )
        else:
            request_context = QuizBankRequestContext(
                seen_item_ids=seen_item_ids,
                target_level=session.level,
                session_type=self._session_flow(session),
            )

        if self._entitlement_service is not None:
            await self._entitlement_service.ensure_daily_question_available(
                db,
                user.telegram_user_id,
                session_id=session.id,
                level=session.level,
                theme=session.theme,
            )

        response = await self._quiz_bank_service.request_quiz(
            level=session.level,
            theme=session.theme,
            limit=1,
            user_context=request_context,
        )

        if response.returned_count < 1 or not response.items:
            if is_review_session and self._mistakes_service is not None and mistake_item_ids:
                await self._mistakes_service.mark_review_items_unavailable(
                    db,
                    user.telegram_user_id,
                    external_quiz_ids=mistake_item_ids,
                    session_id=session.id,
                )
            await self._session_repo.mark_failed(db, session)
            await self._session_repo.clear_pending_question(db, session)
            await db.flush()
            raise NoMoreQuestionsError("Quiz Bank returned no questions")

        first = response.items[0]
        question_reference = await self._question_reference_repo.upsert_snapshot(
            db,
            item_id=first.item_id,
            level=first.level,
            theme=first.theme,
            theme_key=first.theme_key,
            metadata_snapshot=question_metadata_snapshot(first),
            content_version=first.content_version,
            question_text_snapshot=normalize_text(first.question_text),
            correct_answer_snapshot=answer_text(first, first.correct_answer.option_id),
            explanation_snapshot=normalize_explanation(first.explanation),
        )
        await db.flush()
        existing_session_item = await self._session_item_repo.get_by_session_item(
            db,
            session_id=session.id,
            item_id=first.item_id,
        )
        session_item = await self._session_item_repo.create_shown(
            db,
            session_id=session.id,
            user_id=user.id,
            question_reference_id=question_reference.id,
            item_id=first.item_id,
            position=answered + 1,
        )
        if hasattr(self._session_repo, "increment_shown_questions_count") and existing_session_item is None:
            await self._session_repo.increment_shown_questions_count(db, session, 1)
        if existing_session_item is None and self._entitlement_service is not None:
            limit_state = await self._entitlement_service.charge_daily_question(
                db,
                user.telegram_user_id,
            )
            if hasattr(self._session_item_repo, "mark_daily_limit_charged"):
                await self._session_item_repo.mark_daily_limit_charged(
                    db,
                    session_item,
                    daily_limit_id=limit_state.daily_limit.id,
                )
        elif hasattr(self._session_item_repo, "mark_daily_limit_charged"):
            await self._session_item_repo.mark_daily_limit_charged(db, session_item)
        await db.flush()
        payload = build_question_payload(
            session_id=session.id,
            question=first,
            position=answered + 1,
            total_questions=session.total_questions,
            question_reference_id=question_reference.id,
            training_session_item_id=session_item.id,
        )

        await self._session_repo.set_pending_question(db, session, serialize_question_payload(payload))

        api_metadata = dict(session.api_metadata or {})
        api_metadata["requested_count"] = response.requested_count
        api_metadata["returned_count"] = response.returned_count
        api_metadata["has_more"] = response.has_more
        await self._session_repo.set_api_metadata(db, session, api_metadata)
        await db.flush()
        return payload

    async def get_current_question(self, db: AsyncSession, telegram_user_id: int) -> QuizQuestionPayload:
        return await self.get_or_create_current_question(db, telegram_user_id, force_refresh=False)

    async def get_next_question(
        self,
        db: AsyncSession,
        telegram_user_id: int,
        *,
        session_id: int | None = None,
        answered_question_token: str | None = None,
    ) -> QuizQuestionPayload:
        if session_id is not None or answered_question_token is not None:
            active = await self.get_active_session(db, telegram_user_id)
            if active is None or active.id != session_id:
                raise ActiveSessionNotFoundError("Session is not active")
            metadata = active.api_metadata or {}
            pending_raw = metadata.get("pending_question") if isinstance(metadata, dict) else None
            if not isinstance(pending_raw, dict):
                raise QuestionStateError("No active question in session")
            pending = deserialize_question_payload(pending_raw)
            if pending.question_token != answered_question_token:
                raise QuestionStateError("Question token is stale")
        return await self.get_or_create_current_question(db, telegram_user_id, force_refresh=True)

    async def submit_answer(
        self,
        db: AsyncSession,
        telegram_user_id: int,
        session_id: int,
        question_token: str,
        selected_option_id: str,
    ) -> AnswerResult:
        user = await self.get_user(db, telegram_user_id)

        session = await self._session_repo.get_by_id_for_user(db, session_id, user.id)
        if not session:
            raise ActiveSessionNotFoundError("Session is not found")
        if session.status != self.ACTIVE_SESSION_STATUS:
            raise ActiveSessionNotFoundError("Session is not active")

        metadata = session.api_metadata or {}
        pending_raw = metadata.get("pending_question")
        if not isinstance(pending_raw, dict):
            raise QuestionStateError("No active question in session")

        pending = deserialize_question_payload(pending_raw)
        if pending.question_token != question_token or pending.session_id != session.id:
            raise QuestionStateError("Question token is stale")
        if selected_option_id not in option_ids(pending):
            raise QuestionStateError("Selected answer is invalid")

        correct_answer_text = pending.correct_answer_text or option_text(pending, pending.correct_answer)
        answer = None
        mistake = None
        new_mistakes_count = 0

        existing = await self._answer_repo.get_by_session_and_question(
            db,
            session_id=session.id,
            user_id=user.id,
            external_quiz_id=pending.question_id,
        )
        if existing is not None:
            total_answers = await self._answer_repo.count_by_session(db, session.id)
            return AnswerResult(
                selected_answer=selected_option_id,
                correct_answer=pending.correct_answer,
                question_token=pending.question_token,
                is_correct=existing.is_correct,
                is_duplicate=True,
                is_completed=total_answers >= session.total_questions,
                explanation=pending.explanation,
                correct_answers=session.correct_answers,
                total_questions=session.total_questions,
                session_id=session.id,
                correct_answer_text=correct_answer_text,
            )

        is_correct = selected_option_id == pending.correct_answer
        try:
            answer = await self._answer_repo.create(
                db,
                session_id=session.id,
                user_id=user.id,
                external_quiz_id=pending.question_id,
                selected_answer=selected_option_id,
                correct_answer=pending.correct_answer,
                is_correct=is_correct,
                training_session_item_id=pending.training_session_item_id,
                question_reference_id=pending.question_reference_id,
                quiz_source=self.QUIZ_SOURCE,
                level=pending.level,
                theme=pending.theme,
                theme_key=pending.theme_key,
                session_type=self._session_flow(session),
                metadata_snapshot=pending.metadata_snapshot,
            )
            if hasattr(self._session_repo, "increment_answered_count"):
                await self._session_repo.increment_answered_count(db, session, 1)
            session_item = await self._session_item_repo.get_by_session_item(
                db,
                session_id=session.id,
                item_id=pending.question_id,
            )
            if session_item is not None:
                await self._session_item_repo.mark_answered(db, session_item)
            await db.flush()
        except IntegrityError:
            await db.rollback()
            existing = await self._answer_repo.get_by_session_and_question(
                db,
                session_id=session.id,
                user_id=user.id,
                external_quiz_id=pending.question_id,
            )
            if existing is None:
                raise

            total_answers = await self._answer_repo.count_by_session(db, session.id)
            return AnswerResult(
                selected_answer=selected_option_id,
                correct_answer=pending.correct_answer,
                question_token=pending.question_token,
                is_correct=existing.is_correct,
                is_duplicate=True,
                is_completed=total_answers >= session.total_questions,
                explanation=pending.explanation,
                correct_answers=session.correct_answers,
                total_questions=session.total_questions,
                session_id=session.id,
                correct_answer_text=correct_answer_text,
            )

        if is_correct:
            await self._session_repo.increment_correct_answers(db, session, 1)

        if self._mistakes_service is not None:
            if is_correct:
                if self._is_review_session(session):
                    await self._mistakes_service.record_review_success(
                        db,
                        telegram_user_id,
                        external_quiz_id=pending.question_id,
                        question_level=pending.level,
                        question_theme=pending.theme,
                        correct_answer=pending.correct_answer,
                        session_id=session.id,
                        user_answer_id=getattr(answer, "id", None),
                        metadata_snapshot=pending.metadata_snapshot,
                    )
            else:
                mistake = await self._mistakes_service.record_wrong_answer(
                    db,
                    telegram_user_id,
                    external_quiz_id=pending.question_id,
                    level=pending.level,
                    theme=pending.theme,
                    wrong_answer=selected_option_id,
                    correct_answer=pending.correct_answer,
                    source_snapshot={
                        "session_type": self._session_flow(session),
                        "question_token": pending.question_token,
                        "metadata_snapshot": pending.metadata_snapshot,
                    },
                    session_id=session.id,
                    user_answer_id=getattr(answer, "id", None),
                    metadata_snapshot=pending.metadata_snapshot,
                )
                if mistake is not None and int(getattr(mistake, "mistake_count", 0) or 0) == 1:
                    new_mistakes_count = 1

        if not existing and self._progress_service is not None:
            await self._progress_service.record_answer_result(
                db,
                user.telegram_user_id,
                level=pending.level,
                theme=pending.theme,
                is_correct=is_correct,
                is_duplicate=False,
                session_id=session.id,
                user_answer_id=getattr(answer, "id", None),
                item_id=pending.question_id,
                theme_key=pending.theme_key,
                metadata_snapshot=pending.metadata_snapshot,
                reason_code="answer_accepted",
            )

        await self._record_analytics(
            db,
            event_name="question_answered",
            user_id=user.id,
            session_id=session.id,
            event_metadata={
                "session_type": self._session_flow(session),
                "level": pending.level,
                "theme": pending.theme,
                "item_id": pending.question_id,
                "is_correct": is_correct,
                "position": pending.position,
            },
        )

        total_answers = await self._answer_repo.count_by_session(db, session.id)
        completed = total_answers >= session.total_questions
        weak_theme = None
        recommendation_text = None
        if completed:
            await self._session_repo.mark_completed(db, session)
            await self._session_repo.clear_pending_question(db, session)
            weak_theme, recommendation_text = await self._completion_context(
                db,
                user.telegram_user_id,
                new_mistakes_count=new_mistakes_count,
            )
            completion_metadata = {
                "session_type": self._session_flow(session),
                "level": session.level,
                "theme": session.theme,
                "answered_count": total_answers,
                "correct_answers": session.correct_answers,
                "planned_question_count": session.total_questions,
            }
            await self._record_analytics(
                db,
                event_name="training_completed",
                user_id=user.id,
                session_id=session.id,
                event_metadata=completion_metadata,
            )
            await self._record_analytics(
                db,
                event_name="result_shown",
                user_id=user.id,
                session_id=session.id,
                event_metadata=completion_metadata,
            )

        await db.flush()

        return AnswerResult(
            selected_answer=selected_option_id,
            correct_answer=pending.correct_answer,
            question_token=pending.question_token,
            is_correct=is_correct,
            is_duplicate=False,
            is_completed=completed,
            explanation=pending.explanation,
            correct_answers=session.correct_answers,
            total_questions=session.total_questions,
            session_id=session.id,
            correct_answer_text=correct_answer_text,
            weak_theme=weak_theme,
            new_mistakes_count=new_mistakes_count,
            recommendation_text=recommendation_text,
        )
