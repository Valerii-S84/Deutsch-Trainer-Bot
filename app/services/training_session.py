from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.quiz_bank import QuizBankService
from app.quiz_bank.errors import (
    QuizBankAuthError,
    QuizBankError,
    QuizBankRateLimitError,
    QuizBankUnavailableError,
    QuizBankValidationError,
)
from app.services.entitlements import EntitlementService
from app.services.analytics import AnalyticsTracker
from app.services.progress import ProgressService
from app.services.mistakes import MistakeService
from app.services.training_session_lifecycle import TrainingSessionLifecycleMixin
from app.services.training_answer_flow import TrainingAnswerProcessor
from app.services.training_question_flow import TrainingQuestionProcessor
from app.services.training_payloads import (
    ActiveSessionConflictError,
    ActiveSessionNotFoundError,
    AnswerResult,
    NoMoreQuestionsError,
    NoReviewItemsError,
    QuestionStateError,
    QuizQuestionPayload,
    deserialize_question_payload,
)
from app.repositories.answers import AnswerRepository
from app.repositories.analytics_events import AnalyticsEventRepository
from app.repositories.api_error_logs import ApiErrorLogRepository
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
        api_error_log_repo: ApiErrorLogRepository | None = None,
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
        self._api_error_log_repo = api_error_log_repo or ApiErrorLogRepository()
        self._question_reference_repo = question_reference_repo or QuestionReferenceRepository()
        self._session_item_repo = session_item_repo or TrainingSessionItemRepository()
        self._quiz_service = quiz_service
        self._progress_service = progress_service
        self._mistakes_service = mistakes_service
        self._entitlement_service = entitlement_service
        self._analytics_tracker = AnalyticsTracker(self._analytics_repo)

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
        await self._analytics_tracker.record(
            db,
            event_name=event_name,
            user_id=user_id,
            session_id=session_id,
            event_metadata=event_metadata,
            source="training",
        )

    async def _record_quiz_bank_error(
        self,
        db: AsyncSession,
        error: QuizBankError,
        *,
        user_id: int | None,
        session_id: int | None,
        level: str | None,
        theme: str | None,
    ) -> None:
        await self._api_error_log_repo.record(
            db,
            endpoint=error.endpoint or "unknown",
            error_category=_quiz_bank_error_category(error),
            user_id=user_id,
            session_id=session_id,
            request_id=error.request_id,
            status_code=error.status_code,
            level=level,
            theme=theme,
            error_metadata={"message": error.message},
        )
        event_name = "quiz_api_invalid_response" if isinstance(error, QuizBankValidationError) else "quiz_api_request_failed"
        await self._record_analytics(
            db,
            event_name=event_name,
            user_id=user_id,
            session_id=session_id,
            event_metadata={
                "endpoint": error.endpoint or "unknown",
                "error_category": _quiz_bank_error_category(error),
                "status_code": error.status_code,
                "level": level,
                "theme": theme,
            },
        )

    async def _available_items_count_for_question(
        self,
        db: AsyncSession,
        *,
        user_id: int,
        session_id: int,
        level: str,
        theme: str | None,
    ) -> int | None:
        if not theme:
            return None
        quiz_service = self._quiz_bank_service
        if not hasattr(quiz_service, "get_availability"):
            return None
        try:
            availability = await quiz_service.get_availability(level=level, theme=theme)
        except QuizBankError as exc:
            await self._record_quiz_bank_error(
                db,
                exc,
                user_id=user_id,
                session_id=session_id,
                level=level,
                theme=theme,
            )
            return None
        return availability.available_items_count

    async def _get_answer_by_update_id(
        self,
        db: AsyncSession,
        telegram_update_id: int | None,
    ):
        if telegram_update_id is None:
            return None
        if not hasattr(self._answer_repo, "get_by_telegram_update_id"):
            return None
        return await self._answer_repo.get_by_telegram_update_id(db, telegram_update_id)

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
        return await TrainingQuestionProcessor(self).get_or_create_current_question(
            db,
            telegram_user_id,
            force_refresh=force_refresh,
        )

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
        telegram_update_id: int | None = None,
    ) -> AnswerResult:
        return await TrainingAnswerProcessor(self).submit_answer(
            db,
            telegram_user_id,
            session_id,
            question_token,
            selected_option_id,
            telegram_update_id=telegram_update_id,
        )


def _quiz_bank_error_category(error: QuizBankError) -> str:
    if isinstance(error, QuizBankAuthError):
        return "auth"
    if isinstance(error, QuizBankRateLimitError):
        return "rate_limit"
    if isinstance(error, QuizBankValidationError):
        return "validation"
    if isinstance(error, QuizBankUnavailableError):
        return "unavailable"
    return "unknown"
