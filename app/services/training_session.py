from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha1
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.quiz_bank import QuizBankRequestContext, QuizBankService
from app.quiz_bank.schemas import QuizItem
from app.services.progress import ProgressService
from app.services.mistakes import MistakeService
from app.repositories.answers import AnswerRepository
from app.repositories.quiz_sessions import QuizSessionRepository, QuizSessionStatus
from app.repositories.users import UserRepository


@dataclass(frozen=True)
class QuizQuestionPayload:
    session_id: int
    question_token: str
    question_id: str
    question_text: str
    answer_options: tuple[tuple[str, str], ...]
    correct_answer: str
    explanation: str | None
    position: int
    total_questions: int
    level: str
    theme: str | None


@dataclass(frozen=True)
class AnswerResult:
    selected_answer: str
    correct_answer: str
    question_token: str
    is_correct: bool
    is_duplicate: bool
    is_completed: bool
    explanation: str | None
    correct_answers: int
    total_questions: int
    session_id: int


class TrainingFlowError(Exception):
    """Base error for the training flow."""


class ActiveSessionConflictError(TrainingFlowError):
    """Raised when an active session already exists."""


class ActiveSessionNotFoundError(TrainingFlowError):
    """Raised when an active session does not exist for the user."""


class QuestionStateError(TrainingFlowError):
    """Raised when pending question state is missing or invalid."""


class NoMoreQuestionsError(TrainingFlowError):
    """Raised when the Quiz Bank returns no available questions."""


class NoReviewItemsError(TrainingFlowError):
    """Raised when review flow has no active mistake items."""


class TrainingSessionService:
    """Runtime session orchestration without progress/mistake side effects."""

    ACTIVE_SESSION_STATUS = QuizSessionStatus.active
    COMPLETED_SESSION_STATUS = QuizSessionStatus.completed
    CANCELLED_SESSION_STATUS = QuizSessionStatus.cancelled
    FAILED_SESSION_STATUS = QuizSessionStatus.failed
    DEFAULT_SESSION_QUESTIONS = 5
    QUIZ_SOURCE = "quiz_bank_api"
    SESSION_FLOW_REGULAR = "regular"
    SESSION_FLOW_REVIEW = "mistake_review"

    def __init__(
        self,
        *,
        user_repo: UserRepository | None = None,
        session_repo: QuizSessionRepository | None = None,
        answer_repo: AnswerRepository | None = None,
        quiz_service: QuizBankService | None = None,
        progress_service: ProgressService | None = None,
        mistakes_service: MistakeService | None = None,
    ) -> None:
        self._user_repo = user_repo or UserRepository()
        self._session_repo = session_repo or QuizSessionRepository()
        self._answer_repo = answer_repo or AnswerRepository()
        self._quiz_service = quiz_service
        self._progress_service = progress_service
        self._mistakes_service = mistakes_service

    @property
    def _quiz_bank_service(self) -> QuizBankService:
        if self._quiz_service is None:
            self._quiz_service = QuizBankService()
        return self._quiz_service

    @staticmethod
    def _normalize_text(value: str | None) -> str:
        return (value or "").strip()

    @staticmethod
    def _normalize_explanation(explanation: str | Any | None) -> str | None:
        if explanation is None:
            return None
        if hasattr(explanation, "text"):
            return TrainingSessionService._normalize_text(getattr(explanation, "text", ""))
        return TrainingSessionService._normalize_text(str(explanation)) or None

    @staticmethod
    def _question_token(external_quiz_id: str) -> str:
        return sha1(external_quiz_id.encode("utf-8")).hexdigest()[:8]

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

    async def start_session(
        self,
        db: AsyncSession,
        telegram_user_id: int,
        level: str,
        theme: str | None,
        *,
        total_questions: int,
        force_new: bool,
    ):
        user = await self.get_user(db, telegram_user_id)
        await self._user_repo.set_training_preferences(db, telegram_user_id, level=level, theme=theme)

        existing = await self._session_repo.get_active_for_user(db, user.id)
        if existing is not None:
            if not force_new:
                raise ActiveSessionConflictError("Active training session exists")
            await self._session_repo.mark_cancelled(db, existing)

        session = await self._session_repo.create(
            db,
            user_id=user.id,
            level=level,
            theme=theme,
            total_questions=max(1, total_questions),
            source=self.QUIZ_SOURCE,
            source_metadata=self._default_source_metadata(self.SESSION_FLOW_REGULAR, telegram_user_id),
            api_metadata={"started_at": datetime.now(UTC).isoformat()},
        )
        await db.flush()
        return session

    async def start_review_session(
        self,
        db: AsyncSession,
        telegram_user_id: int,
        *,
        force_new: bool,
        total_questions: int,
    ):
        if self._mistakes_service is None:
            raise NoReviewItemsError("Review service is not configured")

        user = await self.get_user(db, telegram_user_id)

        review_items = await self._mistakes_service.get_review_items(db, telegram_user_id)
        if not review_items:
            raise NoReviewItemsError("No active mistakes to review")

        existing = await self._session_repo.get_active_for_user(db, user.id)
        if existing is not None:
            if self._is_review_session(existing):
                if not force_new:
                    return existing
                await self._session_repo.mark_cancelled(db, existing)
            elif not force_new:
                raise ActiveSessionConflictError("Active training session exists")
            else:
                await self._session_repo.mark_cancelled(db, existing)

        first_item = review_items[0]
        total = self._session_question_limit(total_questions, review_items)
        session = await self._session_repo.create(
            db,
            user_id=user.id,
            level=first_item.level,
            theme=first_item.theme,
            total_questions=total,
            source=self.QUIZ_SOURCE,
            source_metadata=self._default_source_metadata(self.SESSION_FLOW_REVIEW, telegram_user_id),
            api_metadata={"review_count": len(review_items)},
        )
        await db.flush()
        return session

    async def resume_or_start_review_session(
        self,
        db: AsyncSession,
        telegram_user_id: int,
        *,
        force_new: bool,
        total_questions: int,
    ) -> tuple[Any, QuizQuestionPayload]:
        session = await self.start_review_session(
            db,
            telegram_user_id,
            force_new=force_new,
            total_questions=total_questions,
        )
        question = await self.get_or_create_current_question(
            db,
            telegram_user_id,
            force_refresh=True,
        )
        return session, question

    async def get_active_session(self, db: AsyncSession, telegram_user_id: int):
        user = await self._user_repo.get_by_telegram_id(db, telegram_user_id)
        if not user:
            return None
        return await self._session_repo.get_active_for_user(db, user.id)

    async def cancel_active_session(self, db: AsyncSession, telegram_user_id: int) -> bool:
        user = await self._user_repo.get_by_telegram_id(db, telegram_user_id)
        if not user:
            return False

        session = await self._session_repo.get_active_for_user(db, user.id)
        if not session:
            return False

        await self._session_repo.mark_cancelled(db, session)
        await self._session_repo.clear_pending_question(db, session)
        await db.flush()
        return True

    def _build_question_payload(
        self,
        session_id: int,
        question: QuizItem,
        *,
        position: int,
        total_questions: int,
    ) -> QuizQuestionPayload:
        return QuizQuestionPayload(
            session_id=session_id,
            question_token=self._question_token(question.item_id),
            question_id=question.item_id,
            question_text=self._normalize_text(question.question_text),
            answer_options=tuple((item.option_id, self._normalize_text(item.text)) for item in question.answer_options),
            correct_answer=question.correct_answer.option_id,
            explanation=self._normalize_explanation(question.explanation),
            position=position,
            total_questions=total_questions,
            level=question.level,
            theme=question.theme,
        )

    def _serialize_question_payload(self, payload: QuizQuestionPayload) -> dict[str, object]:
        return {
            "session_id": payload.session_id,
            "question_token": payload.question_token,
            "question_id": payload.question_id,
            "question_text": payload.question_text,
            "answer_options": [{"option_id": option_id, "text": text} for option_id, text in payload.answer_options],
            "correct_answer": payload.correct_answer,
            "explanation": payload.explanation,
            "position": payload.position,
            "total_questions": payload.total_questions,
            "level": payload.level,
            "theme": payload.theme,
        }

    def _deserialize_question_payload(self, payload: dict[str, object]) -> QuizQuestionPayload:
        options_raw = payload.get("answer_options")
        if not isinstance(options_raw, list):
            raise QuestionStateError("pending question payload is missing options")

        options: list[tuple[str, str]] = []
        for option in options_raw:
            if not isinstance(option, dict):
                raise QuestionStateError("invalid option payload")
            option_id = option.get("option_id")
            text = option.get("text")
            if not isinstance(option_id, str) or not isinstance(text, str):
                raise QuestionStateError("invalid option payload")
            options.append((option_id, text))

        try:
            return QuizQuestionPayload(
                session_id=int(payload["session_id"]),
                question_token=str(payload["question_token"]),
                question_id=str(payload["question_id"]),
                question_text=str(payload["question_text"]),
                answer_options=tuple(options),
                correct_answer=str(payload["correct_answer"]),
                explanation=payload.get("explanation") if isinstance(payload.get("explanation"), str) else None,
                position=int(payload["position"]),
                total_questions=int(payload["total_questions"]),
                level=str(payload["level"]),
                theme=str(payload["theme"]) if payload.get("theme") is not None else None,
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise QuestionStateError("pending question payload is invalid") from exc

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
                payload = self._deserialize_question_payload(pending)
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

        response = await self._quiz_bank_service.request_quiz(
            level=session.level,
            theme=session.theme,
            limit=1,
            user_context=request_context,
        )

        if response.returned_count < 1 or not response.items:
            await self._session_repo.mark_failed(db, session)
            await self._session_repo.clear_pending_question(db, session)
            await db.flush()
            raise NoMoreQuestionsError("Quiz Bank returned no questions")

        first = response.items[0]
        payload = self._build_question_payload(
            session_id=session.id,
            question=first,
            position=answered + 1,
            total_questions=session.total_questions,
        )

        await self._session_repo.set_pending_question(db, session, self._serialize_question_payload(payload))

        api_metadata = dict(session.api_metadata or {})
        api_metadata["requested_count"] = response.requested_count
        api_metadata["returned_count"] = response.returned_count
        api_metadata["has_more"] = response.has_more
        await self._session_repo.set_api_metadata(db, session, api_metadata)
        await db.flush()
        return payload

    async def get_current_question(self, db: AsyncSession, telegram_user_id: int) -> QuizQuestionPayload:
        return await self.get_or_create_current_question(db, telegram_user_id, force_refresh=False)

    async def get_next_question(self, db: AsyncSession, telegram_user_id: int) -> QuizQuestionPayload:
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

        pending = self._deserialize_question_payload(pending_raw)
        if pending.question_token != question_token or pending.session_id != session.id:
            raise QuestionStateError("Question token is stale")

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
            )

        is_correct = selected_option_id == pending.correct_answer
        try:
            await self._answer_repo.create(
                db,
                session_id=session.id,
                user_id=user.id,
                external_quiz_id=pending.question_id,
                selected_answer=selected_option_id,
                correct_answer=pending.correct_answer,
                is_correct=is_correct,
                quiz_source=self.QUIZ_SOURCE,
            )
            if hasattr(self._session_repo, "increment_answered_count"):
                await self._session_repo.increment_answered_count(db, session, 1)
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
                    )
            else:
                await self._mistakes_service.record_wrong_answer(
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
                    },
                )

        if not existing and self._progress_service is not None:
            await self._progress_service.record_answer_result(
                db,
                user.telegram_user_id,
                level=session.level,
                theme=session.theme,
                is_correct=is_correct,
                is_duplicate=False,
            )

        total_answers = await self._answer_repo.count_by_session(db, session.id)
        completed = total_answers >= session.total_questions
        if completed:
            await self._session_repo.mark_completed(db, session)
            await self._session_repo.clear_pending_question(db, session)

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
        )

    async def resume_or_start_session(
        self,
        db: AsyncSession,
        telegram_user_id: int,
        level: str,
        theme: str,
        *,
        force_new: bool,
        total_questions: int,
    ) -> tuple[Any, QuizQuestionPayload]:
        session = await self.start_session(
            db,
            telegram_user_id,
            level=level,
            theme=theme,
            total_questions=total_questions,
            force_new=force_new,
        )
        question = await self.get_or_create_current_question(db, telegram_user_id, force_refresh=True)
        return session, question
