"""Training entry points triggered by main-menu messages."""

from __future__ import annotations

from typing import Any

from app.bot.texts import TRAINING_SESSION_ERROR_TEXT, TRAINING_SESSION_RESUME_TEXT
from app.logging_config import log_exception_summary
from app.quiz_bank.errors import (
    QuizBankAuthError,
    QuizBankRateLimitError,
    QuizBankUnavailableError,
    QuizBankValidationError,
)
from app.services.entitlements import DailyLimitExceededError
from app.services.training_session import (
    ActiveSessionConflictError,
    ActiveSessionNotFoundError,
    NoMoreQuestionsError,
    QuestionStateError,
)


_CONTINUE_ERRORS = (
    ActiveSessionNotFoundError,
    NoMoreQuestionsError,
    QuestionStateError,
    QuizBankAuthError,
    QuizBankRateLimitError,
    QuizBankUnavailableError,
    QuizBankValidationError,
    DailyLimitExceededError,
)
_THEME_OPEN_ERRORS = (
    QuizBankAuthError,
    QuizBankRateLimitError,
    QuizBankUnavailableError,
    QuizBankValidationError,
    NoMoreQuestionsError,
    DailyLimitExceededError,
)


async def continue_active_training_from_message(message: Any, user_id: int) -> bool:
    from app.bot.handlers import training

    async with training._session_factory() as db:
        session = await training.training_service.get_active_session(db, user_id)
        if session is None:
            return False
        question = await _load_current_question(training, db, message, user_id, session)
        if question is None:
            return True

    await training._send_question(message, question)
    return True


async def _load_current_question(training: Any, db: Any, message: Any, user_id: int, session: Any) -> Any | None:
    try:
        question = await training.training_service.get_or_create_current_question(db, user_id, force_refresh=False)
        await db.commit()
        return question
    except _CONTINUE_ERRORS as exc:
        await db.rollback()
        await _answer_continue_error(training, message, user_id, session, exc)
        return None


async def _answer_continue_error(training: Any, message: Any, user_id: int, session: Any, error: Exception) -> None:
    if isinstance(error, (QuizBankAuthError, QuizBankRateLimitError, QuizBankUnavailableError, QuizBankValidationError)):
        await training._persist_quiz_bank_error(
            user_id,
            error,
            level=getattr(session, "level", None),
            theme=getattr(session, "theme", None),
        )
        await message.answer(training._map_quizbank_error(error))
    elif isinstance(error, DailyLimitExceededError):
        await training._send_daily_limit_paywall(message)
    else:
        await message.answer(training._map_session_error(error))


async def start_saved_theme_training_from_message(message: Any, user_id: int, *, level: str, theme: str) -> None:
    from app.bot.handlers import training

    async with training._session_factory() as db:
        question = await _open_saved_theme(training, db, message, user_id, level=level, theme=theme)
        if question is None:
            return

    await training._send_question(message, question)


async def _open_saved_theme(
    training: Any,
    db: Any,
    message: Any,
    user_id: int,
    *,
    level: str,
    theme: str,
) -> Any | None:
    try:
        return await training._open_theme_training(db, message, user_id, level=level, theme=theme)
    except ActiveSessionConflictError:
        await message.answer(TRAINING_SESSION_RESUME_TEXT)
    except _THEME_OPEN_ERRORS as exc:
        await db.rollback()
        await training._handle_theme_open_error(message, user_id, exc, level=level, theme=theme)
    except Exception as exc:
        log_exception_summary(
            training.logger,
            "saved_theme_training_open_unexpected_failed",
            exc,
            telegram_user_id=user_id,
            level=level,
            theme=theme,
        )
        await db.rollback()
        await message.answer(TRAINING_SESSION_ERROR_TEXT)
    return None
