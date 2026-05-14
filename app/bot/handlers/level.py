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
    TRAINING_PROMPT,
)

router = Router(name="level")


@router.callback_query(F.data == CALLBACK_LEVELS)
async def open_level_selection(callback_query: CallbackQuery) -> None:
    """Open level chooser."""
    await callback_query.answer()
    if callback_query.message is not None:
        await callback_query.message.answer(TRAINING_PROMPT, reply_markup=build_levels_keyboard())


@router.callback_query(F.data.startswith(CALLBACK_LEVEL_PREFIX))
async def level_selected(callback_query: CallbackQuery) -> None:
    """Process chosen level and move user to theme placeholder menu."""
    await callback_query.answer()
    level = (callback_query.data or "").replace(CALLBACK_LEVEL_PREFIX, "", 1)
    if level not in LEVELS:
        if callback_query.message is not None:
            await callback_query.message.answer(LEVEL_CALLBACK_FALLBACK_TEXT)
        return

    if callback_query.message is not None:
        await callback_query.message.answer(
            LEVEL_SELECTED_TEXT.format(level=level),
            reply_markup=build_theme_keyboard(selected_level=level),
        )
