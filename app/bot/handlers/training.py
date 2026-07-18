"""Training session handlers."""

from __future__ import annotations

import logging
from typing import Any

from aiogram import F, Router
from aiogram.types import CallbackQuery, Update

from app.bot.keyboards.levels import build_levels_keyboard
from app.bot.keyboards.quiz import build_resume_keyboard
from app.bot.handlers.common import session_factory as _session_factory
from app.bot.handlers.training_flow import (
    extract_update_id as _extract_update_id,
    extract_user_id as _extract_user_id,
    map_quizbank_error as _map_quizbank_error,
    map_session_error as _map_session_error,
    parse_answer_payload as _parse_answer_payload,
    parse_next_payload as _parse_next_payload,
    parse_session_payload as _parse_session_payload,
    parse_theme_payload as _parse_theme_payload,
    pending_question_token as _pending_question_token,
    persist_quiz_bank_error,
    send_answer_result as _send_answer_result,
    send_daily_limit_paywall as _send_daily_limit_paywall,
    send_question as _send_question,
)
from app.logging_config import log_exception_summary
from app.bot.texts import (
    CALLBACK_TRAIN_ANSWER_PREFIX,
    CALLBACK_TRAIN_CANCEL_PREFIX,
    CALLBACK_TRAIN_NEXT_PREFIX,
    CALLBACK_TRAIN_NEW_PREFIX,
    CALLBACK_TRAIN_RESUME_PREFIX,
    CALLBACK_THEME_PREFIX,
    LEVELS,
    TRAINING_NO_LEVEL_SELECTED_TEXT,
    TRAINING_RESUME_NO_ACTIVE_TEXT,
    TRAINING_SESSION_CANCELLED_TEXT,
    TRAINING_SESSION_COMPLETED_TEXT,
    TRAINING_SESSION_ERROR_TEXT,
    TRAINING_SESSION_RESUME_TEXT,
    TRAINING_THEME_NOT_AVAILABLE_TEXT,
)
from app.quiz_bank.errors import (
    QuizBankAuthError,
    QuizBankError,
    QuizBankRateLimitError,
    QuizBankUnavailableError,
    QuizBankValidationError,
)
from app.repositories.api_error_logs import ApiErrorLogRepository
from app.repositories.users import UserRepository
from app.runtime.timing import begin_timing, end_timing
from app.runtime.webhook_profiling import merge_webhook_metrics, merge_webhook_timings, webhook_timing_span
from app.services.analytics import AnalyticsTracker
from app.services.training_session import (
    ActiveSessionConflictError,
    ActiveSessionNotFoundError,
    NoMoreQuestionsError,
    QuestionStateError,
    TrainingSessionService,
)
from app.services.entitlements import DailyLimitExceededError, EntitlementService
from app.services.mistakes import MistakeService

logger = logging.getLogger(__name__)

router = Router(name="training")


training_service = TrainingSessionService(
    mistakes_service=MistakeService(),
    entitlement_service=EntitlementService(),
)
_api_error_log_repo = ApiErrorLogRepository()
_user_repo = UserRepository()
_analytics_tracker = AnalyticsTracker()
_NEW_TRAINING_RECOVERABLE_ERRORS = (
    QuizBankAuthError,
    QuizBankRateLimitError,
    QuizBankUnavailableError,
    QuizBankValidationError,
    NoMoreQuestionsError,
    DailyLimitExceededError,
)
_QUESTION_FLOW_RECOVERABLE_ERRORS = (
    ActiveSessionNotFoundError,
    QuestionStateError,
    *_NEW_TRAINING_RECOVERABLE_ERRORS,
)


async def _persist_quiz_bank_error(
    telegram_user_id: int | None,
    error: QuizBankError,
    *,
    level: str | None,
    theme: str | None,
) -> None:
    await persist_quiz_bank_error(
        _session_factory,
        _user_repo,
        _api_error_log_repo,
        _analytics_tracker,
        telegram_user_id,
        error,
        level=level,
        theme=theme,
    )


async def _answer_invalid_theme_payload(callback_query: CallbackQuery) -> None:
    callback_data = callback_query.data or ""
    if _theme_payload_needs_level(callback_data):
        await callback_query.message.answer(TRAINING_NO_LEVEL_SELECTED_TEXT, reply_markup=build_levels_keyboard())
        return
    await callback_query.message.answer(TRAINING_THEME_NOT_AVAILABLE_TEXT)


def _theme_payload_needs_level(callback_data: str) -> bool:
    return (
        callback_data.startswith(CALLBACK_THEME_PREFIX)
        and (callback_data.count(":") == 1 or callback_data.startswith(f"{CALLBACK_THEME_PREFIX}:"))
    )


async def _record_theme_selected(db: Any, user_id: int, *, level: str, theme: str) -> None:
    internal_user_id = None
    if hasattr(db, "get_bind"):
        user = await _user_repo.set_training_preferences(db, user_id, level=level, theme=theme)
        if getattr(user, "id", None) is None and hasattr(db, "flush"):
            await db.flush()
        internal_user_id = getattr(user, "id", None)
    await _analytics_tracker.record(
        db,
        event_name="theme_selected",
        user_id=internal_user_id,
        event_metadata={"level": level, "theme": theme},
        source="onboarding",
    )


async def _open_theme_training(db: Any, message: Any, user_id: int, *, level: str, theme: str):
    await _record_theme_selected(db, user_id, level=level, theme=theme)
    active = await training_service.get_active_session(db, user_id)
    if active is not None:
        await db.commit()
        await message.answer(
            TRAINING_SESSION_RESUME_TEXT,
            reply_markup=build_resume_keyboard(active.id),
        )
        return None

    _, question = await training_service.resume_or_start_session(
        db,
        user_id,
        level=level,
        theme=theme,
        force_new=False,
        total_questions=TrainingSessionService.DEFAULT_SESSION_QUESTIONS,
    )
    await db.commit()
    return question


async def _handle_theme_open_error(message: Any, user_id: int, error: Exception, *, level: str, theme: str) -> None:
    if isinstance(error, DailyLimitExceededError):
        await _send_daily_limit_paywall(message)
        return
    if isinstance(error, QuizBankError):
        await _persist_quiz_bank_error(user_id, error, level=level, theme=theme)
    await message.answer(_map_quizbank_error(error))


async def _answer_new_training_unexpected_error(
    db: Any,
    message: Any,
    user_id: int,
    session_id: int,
    error: Exception,
) -> None:
    log_exception_summary(
        logger,
        "new_training_start_failed",
        error,
        telegram_user_id=user_id,
        session_id=session_id,
    )
    await db.rollback()
    await message.answer(TRAINING_SESSION_ERROR_TEXT)


@router.callback_query(F.data.startswith(CALLBACK_THEME_PREFIX))
async def handle_theme_selected(callback_query: CallbackQuery) -> None:
    await callback_query.answer()
    if callback_query.message is None:
        return

    user_id = _extract_user_id(callback_query)
    if not user_id:
        return

    try:
        level, theme = _parse_theme_payload(callback_query.data)
    except ValueError:
        await _answer_invalid_theme_payload(callback_query)
        return

    if level not in LEVELS:
        await callback_query.message.answer(TRAINING_THEME_NOT_AVAILABLE_TEXT)
        return

    async with _session_factory() as db:
        try:
            question = await _open_theme_training(db, callback_query.message, user_id, level=level, theme=theme)
            if question is None:
                return
        except ActiveSessionConflictError:
            await callback_query.message.answer(TRAINING_SESSION_RESUME_TEXT)
            return
        except (
            QuizBankAuthError,
            QuizBankRateLimitError,
            QuizBankUnavailableError,
            QuizBankValidationError,
            NoMoreQuestionsError,
            DailyLimitExceededError,
        ) as exc:
            await db.rollback()
            await _handle_theme_open_error(callback_query.message, user_id, exc, level=level, theme=theme)
            return
        except Exception as exc:
            log_exception_summary(
                logger,
                "theme_training_open_unexpected_failed",
                exc,
                telegram_user_id=user_id,
                level=level,
                theme=theme,
            )
            await db.rollback()
            await callback_query.message.answer(TRAINING_SESSION_ERROR_TEXT)
            return

    await _send_question(callback_query.message, question)


@router.callback_query(F.data.startswith(CALLBACK_TRAIN_RESUME_PREFIX + ":"))
async def handle_resume_training(callback_query: CallbackQuery) -> None:
    await callback_query.answer()
    if callback_query.message is None:
        return

    user_id = _extract_user_id(callback_query)
    if not user_id:
        return

    try:
        session_id = _parse_session_payload(callback_query.data, CALLBACK_TRAIN_RESUME_PREFIX)
    except ValueError:
        await callback_query.message.answer(TRAINING_SESSION_ERROR_TEXT)
        return

    async with _session_factory() as db:
        session = await training_service.get_active_session(db, user_id)
        if session is None or session.id != session_id:
            await callback_query.message.answer(TRAINING_RESUME_NO_ACTIVE_TEXT)
            return

        try:
            question = await training_service.get_or_create_current_question(db, user_id, force_refresh=False)
            await db.commit()
        except _QUESTION_FLOW_RECOVERABLE_ERRORS as exc:
            await db.rollback()
            if isinstance(
                exc,
                (
                    QuizBankAuthError,
                    QuizBankRateLimitError,
                    QuizBankUnavailableError,
                    QuizBankValidationError,
                ),
            ):
                await _persist_quiz_bank_error(
                    user_id,
                    exc,
                    level=getattr(session, "level", None),
                    theme=getattr(session, "theme", None),
                )
                await callback_query.message.answer(_map_quizbank_error(exc))
            elif isinstance(exc, DailyLimitExceededError):
                await _send_daily_limit_paywall(callback_query.message)
            else:
                await callback_query.message.answer(_map_session_error(exc))
            return

    await _send_question(callback_query.message, question)


@router.callback_query(F.data.startswith(CALLBACK_TRAIN_NEW_PREFIX + ":"))
async def handle_start_new_training(callback_query: CallbackQuery) -> None:
    await callback_query.answer()
    if callback_query.message is None:
        return

    user_id = _extract_user_id(callback_query)
    if not user_id:
        return

    try:
        session_id = _parse_session_payload(callback_query.data, CALLBACK_TRAIN_NEW_PREFIX)
    except ValueError:
        await callback_query.message.answer(TRAINING_SESSION_ERROR_TEXT)
        return

    async with _session_factory() as db:
        active = await training_service.get_active_session(db, user_id)
        if active is None or active.id != session_id:
            await callback_query.message.answer(TRAINING_RESUME_NO_ACTIVE_TEXT)
            return

        try:
            await training_service.start_session(
                db,
                user_id,
                level=active.level,
                theme=active.theme,
                total_questions=TrainingSessionService.DEFAULT_SESSION_QUESTIONS,
                force_new=True,
            )
            question = await training_service.get_or_create_current_question(db, user_id, force_refresh=True)
            await db.commit()
        except _NEW_TRAINING_RECOVERABLE_ERRORS as exc:
            await db.rollback()
            if isinstance(exc, DailyLimitExceededError):
                await _send_daily_limit_paywall(callback_query.message)
            else:
                if isinstance(exc, QuizBankError):
                    await _persist_quiz_bank_error(
                        user_id,
                        exc,
                        level=getattr(active, "level", None),
                        theme=getattr(active, "theme", None),
                    )
                await callback_query.message.answer(_map_quizbank_error(exc))
            return
        except Exception as exc:
            await _answer_new_training_unexpected_error(
                db,
                callback_query.message,
                user_id,
                session_id,
                exc,
            )
            return

    await _send_question(callback_query.message, question)


@router.callback_query(F.data.startswith(CALLBACK_TRAIN_CANCEL_PREFIX + ":"))
async def handle_cancel_training(callback_query: CallbackQuery) -> None:
    await callback_query.answer()
    if callback_query.message is None:
        return

    user_id = _extract_user_id(callback_query)
    if not user_id:
        return

    async with _session_factory() as db:
        try:
            session_id = _parse_session_payload(callback_query.data, CALLBACK_TRAIN_CANCEL_PREFIX)
        except ValueError:
            await callback_query.message.answer(TRAINING_SESSION_ERROR_TEXT)
            return

        try:
            active = await training_service.get_active_session(db, user_id)
            if active is None or active.id != session_id:
                await callback_query.message.answer(TRAINING_RESUME_NO_ACTIVE_TEXT)
                return
            cancelled = await training_service.cancel_active_session(db, user_id)
            await db.commit()
        except Exception as exc:
            log_exception_summary(
                logger,
                "training_cancel_unexpected_failed",
                exc,
                telegram_user_id=user_id,
                session_id=session_id,
            )
            await db.rollback()
            await callback_query.message.answer(TRAINING_SESSION_ERROR_TEXT)
            return

    if cancelled:
        await callback_query.message.answer(TRAINING_SESSION_CANCELLED_TEXT, reply_markup=build_levels_keyboard())
    else:
        await callback_query.message.answer(TRAINING_RESUME_NO_ACTIVE_TEXT)


@router.callback_query(F.data.startswith(CALLBACK_TRAIN_ANSWER_PREFIX + ":"))
async def handle_submit_answer(callback_query: CallbackQuery, event_update: Update | None = None) -> None:
    with webhook_timing_span("handler.training_answer_total_ms"):
        with webhook_timing_span("handler.training_answer_callback_answer_ms"):
            await callback_query.answer()
        if callback_query.message is None:
            return

        user_id = _extract_user_id(callback_query)
        if not user_id:
            return

        try:
            with webhook_timing_span("handler.training_answer_parse_payload_ms"):
                session_id, question_token, selected_option = _parse_answer_payload(callback_query.data)
        except ValueError:
            await callback_query.message.answer(TRAINING_SESSION_ERROR_TEXT)
            return

        result = await _submit_answer_with_db(
            callback_query,
            user_id=user_id,
            session_id=session_id,
            question_token=question_token,
            selected_option=selected_option,
            event_update=event_update,
        )
        if result is None:
            return
        with webhook_timing_span("handler.training_answer_send_result_ms"):
            await _send_answer_result(callback_query.message, result)


async def _submit_answer_with_db(
    callback_query: CallbackQuery,
    *,
    user_id: int,
    session_id: int,
    question_token: str,
    selected_option: str,
    event_update: Update | None,
) -> Any | None:
    async with _session_factory() as db:
        timing_spans, timing_metrics, timing_token = begin_timing()
        try:
            with webhook_timing_span("handler.training_answer_submit_ms"):
                result = await training_service.submit_answer(
                    db,
                    user_id,
                    session_id=session_id,
                    question_token=question_token,
                    selected_option_id=selected_option,
                    telegram_update_id=_extract_update_id(event_update),
                )
            with webhook_timing_span("handler.training_answer_commit_ms"):
                await db.commit()
        except (QuestionStateError, ActiveSessionNotFoundError, NoMoreQuestionsError) as exc:
            await db.rollback()
            await callback_query.message.answer(_map_session_error(exc))
            return None
        finally:
            end_timing(timing_token)
            merge_webhook_timings(timing_spans)
            merge_webhook_metrics(timing_metrics)
    return result


@router.callback_query(F.data.startswith(CALLBACK_TRAIN_NEXT_PREFIX + ":"))
async def handle_next_question(callback_query: CallbackQuery) -> None:
    await callback_query.answer()
    if callback_query.message is None:
        return

    user_id = _extract_user_id(callback_query)
    if not user_id:
        return

    try:
        session_id, question_token = _parse_next_payload(callback_query.data)
    except ValueError:
        await callback_query.message.answer(TRAINING_SESSION_ERROR_TEXT)
        return

    async with _session_factory() as db:
        try:
            active = await training_service.get_active_session(db, user_id)
            if active is None or active.id != session_id:
                await callback_query.message.answer(TRAINING_SESSION_COMPLETED_TEXT)
                return
            if _pending_question_token(active) != question_token:
                await callback_query.message.answer(TRAINING_SESSION_ERROR_TEXT)
                return
            question = await training_service.get_next_question(
                db,
                user_id,
                session_id=session_id,
                answered_question_token=question_token,
            )
            await db.commit()
        except _QUESTION_FLOW_RECOVERABLE_ERRORS as exc:
            await db.rollback()
            if isinstance(exc, (QuizBankAuthError, QuizBankRateLimitError, QuizBankUnavailableError, QuizBankValidationError)):
                await _persist_quiz_bank_error(
                    user_id,
                    exc,
                    level=getattr(active, "level", None),
                    theme=getattr(active, "theme", None),
                )
                await callback_query.message.answer(_map_quizbank_error(exc))
            elif isinstance(exc, DailyLimitExceededError):
                await _send_daily_limit_paywall(callback_query.message)
            else:
                await callback_query.message.answer(_map_session_error(exc))
            return

    await _send_question(callback_query.message, question)
