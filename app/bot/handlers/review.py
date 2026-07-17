"""Review handlers for mistake replay flow."""

from __future__ import annotations

from contextlib import asynccontextmanager
import logging

from aiogram import F, Router
from aiogram.types import CallbackQuery

from app.bot.formatting import escape_markdown_text
from app.bot.handlers.common import extract_user_id as _extract_user_id
from app.bot.handlers.common import map_quizbank_error as _map_quizbank_error
from app.bot.handlers.common import session_factory as _session_factory
from app.bot.keyboards.main_menu import build_back_to_main_menu_button
from app.bot.keyboards.quiz import build_question_options_keyboard
from app.bot.keyboards.review import build_review_empty_keyboard, build_review_screen_keyboard
from app.bot.keyboards.subscription import build_paywall_keyboard
from app.bot.texts import (
    CALLBACK_REVIEW,
    CALLBACK_REVIEW_START,
    REVIEW_EMPTY_STATE_TEXT,
    REVIEW_SCREEN_TEXT,
    TRAINING_QUESTION_TEMPLATE,
    TRAINING_SESSION_ERROR_TEXT,
    TRAINING_SESSION_RESUME_TEXT,
    PAYWALL_MISTAKE_REPEAT_TEXT,
    PAYWALL_DAILY_LIMIT_TEXT,
)
from app.logging_config import log_exception_summary
from app.quiz_bank.errors import (
    QuizBankAuthError,
    QuizBankError,
    QuizBankRateLimitError,
    QuizBankUnavailableError,
    QuizBankValidationError,
)
from app.repositories.api_error_logs import ApiErrorLogRepository
from app.repositories.users import UserRepository
from app.services.analytics import AnalyticsTracker
from app.services.mistakes import MistakeService
from app.services.entitlements import (
    FEATURE_MISTAKE_REPEAT,
    EntitlementDeniedError,
    DailyLimitExceededError,
    EntitlementService,
)
from app.services.training_session import (
    ActiveSessionConflictError,
    NoMoreQuestionsError,
    NoReviewItemsError,
    TrainingSessionService,
)


router = Router(name="review")
logger = logging.getLogger(__name__)

review_service = TrainingSessionService(
    mistakes_service=MistakeService(),
    entitlement_service=EntitlementService(),
)
mistake_service = MistakeService()
entitlement_service = EntitlementService()
_api_error_log_repo = ApiErrorLogRepository()
_user_repo = UserRepository()
_analytics_tracker = AnalyticsTracker()


def _question_message(position: int, total_questions: int, question_text: str) -> str:
    return TRAINING_QUESTION_TEMPLATE.format(
        position=position,
        total=total_questions,
        question_text=escape_markdown_text(question_text),
    )


@asynccontextmanager
async def _session_context():
    db = _session_factory()
    if hasattr(db, "__aenter__") and hasattr(db, "__aexit__"):
        async with db as session:
            yield session
    else:
        try:
            yield db
        except Exception as exc:
            log_exception_summary(logger, "review_session_context_unexpected_failed", exc)
            if hasattr(db, "rollback"):
                await db.rollback()
            raise


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


async def _persist_quiz_bank_error(telegram_user_id: int | None, error: QuizBankError) -> None:
    async with _session_context() as db:
        try:
            user = await _user_repo.get_by_telegram_id(db, telegram_user_id) if telegram_user_id else None
            await _api_error_log_repo.record(
                db,
                endpoint=error.endpoint or "unknown",
                error_category=_quiz_bank_error_category(error),
                user_id=getattr(user, "id", None),
                request_id=error.request_id,
                status_code=error.status_code,
                error_metadata={"message": error.message},
            )
            event_name = "quiz_api_invalid_response" if isinstance(error, QuizBankValidationError) else "quiz_api_request_failed"
            await _analytics_tracker.record(
                db,
                event_name=event_name,
                user_id=getattr(user, "id", None),
                event_metadata={
                    "endpoint": error.endpoint or "unknown",
                    "error_category": _quiz_bank_error_category(error),
                    "status_code": error.status_code,
                },
                source="review",
            )
            await db.commit()
        except Exception as exc:
            log_exception_summary(
                logger,
                "review_quiz_bank_error_persist_failed",
                exc,
                telegram_user_id=telegram_user_id,
                endpoint=error.endpoint or "unknown",
                category=_quiz_bank_error_category(error),
            )
            await db.rollback()


async def _record_review_opened(db, review_items: list[object]) -> None:
    await _analytics_tracker.record(
        db,
        event_name="mistakes_opened",
        user_id=_review_user_id(review_items),
        event_metadata={"active_mistake_count": len(review_items)},
        source="review",
    )


async def _record_review_paywall(db, review_items: list[object]) -> None:
    await _analytics_tracker.record(
        db,
        event_name="paywall_shown",
        user_id=_review_user_id(review_items),
        event_metadata={
            "paywall_context": "mistake_repeat_access",
            "trigger": "mistakes_opened",
            "plan_offered": "plus",
            "active_mistake_count": len(review_items),
        },
        source="review",
    )


def _review_user_id(review_items: list[object]) -> int | None:
    if not review_items:
        return None
    user_id = getattr(review_items[0], "user_id", None)
    return user_id if isinstance(user_id, int) else None


@router.callback_query(F.data == CALLBACK_REVIEW)
async def handle_review_entry(callback_query: CallbackQuery) -> None:
    """Open mistake screen before starting review training."""
    await callback_query.answer()
    if callback_query.message is None:
        return

    user_id = _extract_user_id(callback_query)
    if not user_id:
        return

    async with _session_context() as db:
        review_items: list[object] = []
        try:
            review_items = await mistake_service.get_review_items(db, user_id)
            await _record_review_opened(db, review_items)
            if not review_items:
                if hasattr(db, "commit"):
                    await db.commit()
                await callback_query.message.answer(
                    REVIEW_EMPTY_STATE_TEXT,
                    reply_markup=build_review_empty_keyboard(),
                )
                return
            await entitlement_service.ensure_entitlement(db, user_id, feature=FEATURE_MISTAKE_REPEAT)
            if hasattr(db, "commit"):
                await db.commit()
        except EntitlementDeniedError:
            await db.rollback()
            await _record_review_paywall(db, review_items)
            if hasattr(db, "commit"):
                await db.commit()
            await callback_query.message.answer(
                PAYWALL_MISTAKE_REPEAT_TEXT,
                reply_markup=build_paywall_keyboard(),
            )
            return

    await callback_query.message.answer(
        REVIEW_SCREEN_TEXT,
        reply_markup=build_review_screen_keyboard(),
    )


@router.callback_query(F.data == CALLBACK_REVIEW_START)
async def handle_review_start(callback_query: CallbackQuery) -> None:
    """Start mistake review training after the active Mistake Screen."""
    await callback_query.answer()
    if callback_query.message is None:
        return

    user_id = _extract_user_id(callback_query)
    if not user_id:
        return

    async with _session_context() as db:
        try:
            _, question = await review_service.resume_or_start_review_session(
                db,
                user_id,
                force_new=False,
                total_questions=TrainingSessionService.DEFAULT_SESSION_QUESTIONS,
            )
            await db.commit()
        except NoReviewItemsError:
            await db.rollback()
            await callback_query.message.answer(
                REVIEW_EMPTY_STATE_TEXT,
                reply_markup=build_review_empty_keyboard(),
            )
            return
        except EntitlementDeniedError:
            await db.rollback()
            await callback_query.message.answer(
                PAYWALL_MISTAKE_REPEAT_TEXT,
                reply_markup=build_paywall_keyboard(),
            )
            return
        except DailyLimitExceededError:
            await db.rollback()
            await callback_query.message.answer(
                PAYWALL_DAILY_LIMIT_TEXT,
                reply_markup=build_paywall_keyboard(include_progress=True),
            )
            return
        except ActiveSessionConflictError:
            await db.rollback()
            await callback_query.message.answer(
                TRAINING_SESSION_RESUME_TEXT,
                reply_markup=build_back_to_main_menu_button(),
            )
            return
        except NoMoreQuestionsError:
            await db.rollback()
            await callback_query.message.answer(
                TRAINING_SESSION_ERROR_TEXT,
                reply_markup=build_back_to_main_menu_button(),
            )
            return
        except (QuizBankAuthError, QuizBankRateLimitError, QuizBankUnavailableError, QuizBankValidationError) as exc:
            await db.rollback()
            await _persist_quiz_bank_error(user_id, exc)
            await callback_query.message.answer(
                _map_quizbank_error(exc),
                reply_markup=build_back_to_main_menu_button(),
            )
            return
        except Exception as exc:
            log_exception_summary(logger, "review_start_unexpected_failed", exc, telegram_user_id=user_id)
            await db.rollback()
            await callback_query.message.answer(
                TRAINING_SESSION_ERROR_TEXT,
                reply_markup=build_back_to_main_menu_button(),
            )
            return

    await callback_query.message.answer(
        _question_message(
            position=question.position,
            total_questions=question.total_questions,
            question_text=question.question_text,
        ),
        reply_markup=build_question_options_keyboard(question),
        parse_mode="Markdown",
    )
