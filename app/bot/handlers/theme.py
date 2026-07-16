"""Theme selection handlers."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery

from app.bot.keyboards.levels import build_levels_keyboard
from app.bot.keyboards.themes import build_theme_keyboard
from app.bot.texts import (
    CALLBACK_THEMES,
    THEME_EMPTY_STATE_TEXT,
    THEME_PROMPT,
    TRAINING_NO_LEVEL_SELECTED_TEXT,
    TRAINING_QUIZBANK_UNAVAILABLE_TEXT,
)
from app.bot.handlers.common import extract_user_id as _extract_user_id
from app.bot.handlers.common import map_quizbank_error
from app.bot.handlers.common import session_factory as _session_factory
from app.quiz_bank.errors import QuizBankError
from app.quiz_bank.service import QuizBankService
from app.repositories.users import UserRepository

router = Router(name="theme")
_quiz_service = QuizBankService
_user_repo = UserRepository()


@router.callback_query(F.data == CALLBACK_THEMES)
async def open_theme_selection(callback_query: CallbackQuery) -> None:
    """Open theme chooser directly from menu."""
    await callback_query.answer()
    user_id = _extract_user_id(callback_query)
    if user_id is None:
        if callback_query.message is not None:
            await callback_query.message.answer(TRAINING_NO_LEVEL_SELECTED_TEXT, reply_markup=build_levels_keyboard())
        return

    async with _session_factory() as db:
        user = await _user_repo.get_by_telegram_id(db, user_id)

    selected_level = getattr(user, "selected_level", None)
    if not selected_level:
        if callback_query.message is not None:
            await callback_query.message.answer(TRAINING_NO_LEVEL_SELECTED_TEXT, reply_markup=build_levels_keyboard())
        return

    try:
        themes_response = await _quiz_service().get_themes(level=selected_level)
    except QuizBankError as exc:
        if callback_query.message is not None:
            await callback_query.message.answer(
                map_quizbank_error(exc, default_text=TRAINING_QUIZBANK_UNAVAILABLE_TEXT),
                reply_markup=build_levels_keyboard(),
            )
        return

    if callback_query.message is not None:
        if not themes_response.themes:
            await callback_query.message.answer(THEME_EMPTY_STATE_TEXT, reply_markup=build_levels_keyboard())
            return
        await callback_query.message.answer(
            THEME_PROMPT,
            reply_markup=build_theme_keyboard(selected_level=selected_level, themes=themes_response.themes),
        )
