from __future__ import annotations

from aiogram.types import CallbackQuery, Message

from app.bot.texts import (
    TRAINING_QUIZBANK_AUTH_ERROR_TEXT,
    TRAINING_QUIZBANK_RATE_LIMIT_TEXT,
    TRAINING_QUIZBANK_UNAVAILABLE_TEXT,
    TRAINING_QUIZBANK_VALIDATION_TEXT,
    TRAINING_SESSION_ERROR_TEXT,
)
from app.db.session import get_session
from app.quiz_bank.errors import (
    QuizBankAuthError,
    QuizBankRateLimitError,
    QuizBankUnavailableError,
    QuizBankValidationError,
)


def session_factory():
    return get_session()


def extract_user_id(event: Message | CallbackQuery) -> int | None:
    return getattr(getattr(event, "from_user", None), "id", None)


def map_quizbank_error(error: Exception, *, default_text: str = TRAINING_SESSION_ERROR_TEXT) -> str:
    if isinstance(error, QuizBankAuthError):
        return TRAINING_QUIZBANK_AUTH_ERROR_TEXT
    if isinstance(error, QuizBankRateLimitError):
        return TRAINING_QUIZBANK_RATE_LIMIT_TEXT
    if isinstance(error, QuizBankUnavailableError):
        return TRAINING_QUIZBANK_UNAVAILABLE_TEXT
    if isinstance(error, QuizBankValidationError):
        return TRAINING_QUIZBANK_VALIDATION_TEXT
    return default_text
