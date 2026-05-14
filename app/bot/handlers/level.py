"""Level entrypoint and selection handlers."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery

from app.bot.keyboards.levels import build_levels_keyboard
from app.bot.keyboards.themes import build_theme_keyboard
from app.bot.texts import (
    CALLBACK_LEVELS,
    CALLBACK_LEVEL_PREFIX,
    LEVEL_CALLBACK_FALLBACK_TEXT,
    LEVELS,
    LEVEL_SELECTED_TEXT,
    THEME_EMPTY_STATE_TEXT,
    TRAINING_PROMPT,
    TRAINING_QUIZBANK_AUTH_ERROR_TEXT,
    TRAINING_QUIZBANK_RATE_LIMIT_TEXT,
    TRAINING_QUIZBANK_UNAVAILABLE_TEXT,
    TRAINING_QUIZBANK_VALIDATION_TEXT,
)
from app.db.session import get_session as _get_session
from app.quiz_bank.errors import (
    QuizBankAuthError,
    QuizBankError,
    QuizBankRateLimitError,
    QuizBankUnavailableError,
    QuizBankValidationError,
)
from app.quiz_bank.service import QuizBankService
from app.repositories.users import UserRepository

router = Router(name="level")
_quiz_service = QuizBankService
_user_repo = UserRepository()


def _session_factory():
    return _get_session()


def _extract_user_id(callback_query: CallbackQuery) -> int | None:
    return getattr(getattr(callback_query, "from_user", None), "id", None)


def _map_quizbank_error(error: Exception) -> str:
    if isinstance(error, QuizBankAuthError):
        return TRAINING_QUIZBANK_AUTH_ERROR_TEXT
    if isinstance(error, QuizBankRateLimitError):
        return TRAINING_QUIZBANK_RATE_LIMIT_TEXT
    if isinstance(error, QuizBankUnavailableError):
        return TRAINING_QUIZBANK_UNAVAILABLE_TEXT
    if isinstance(error, QuizBankValidationError):
        return TRAINING_QUIZBANK_VALIDATION_TEXT
    return TRAINING_QUIZBANK_UNAVAILABLE_TEXT


@router.callback_query(F.data == CALLBACK_LEVELS)
async def open_level_selection(callback_query: CallbackQuery) -> None:
    """Open level chooser."""
    await callback_query.answer()
    if callback_query.message is not None:
        await callback_query.message.answer(TRAINING_PROMPT, reply_markup=build_levels_keyboard())


@router.callback_query(F.data.startswith(CALLBACK_LEVEL_PREFIX))
async def level_selected(callback_query: CallbackQuery) -> None:
    """Process chosen level and move user to availability-driven theme menu."""
    await callback_query.answer()
    level = (callback_query.data or "").replace(CALLBACK_LEVEL_PREFIX, "", 1)
    if level not in LEVELS:
        if callback_query.message is not None:
            await callback_query.message.answer(LEVEL_CALLBACK_FALLBACK_TEXT)
        return

    user_id = _extract_user_id(callback_query)
    if user_id is not None:
        async with _session_factory() as db:
            try:
                await _user_repo.set_training_preferences(db, user_id, level=level)
                await db.commit()
            except Exception:
                await db.rollback()

    try:
        themes_response = await _quiz_service().get_themes(level=level)
    except QuizBankError as exc:
        if callback_query.message is not None:
            await callback_query.message.answer(_map_quizbank_error(exc), reply_markup=build_levels_keyboard())
        return

    if callback_query.message is not None:
        if not themes_response.themes:
            await callback_query.message.answer(THEME_EMPTY_STATE_TEXT, reply_markup=build_levels_keyboard())
            return
        await callback_query.message.answer(
            LEVEL_SELECTED_TEXT.format(level=level),
            reply_markup=build_theme_keyboard(selected_level=level, themes=themes_response.themes),
        )
