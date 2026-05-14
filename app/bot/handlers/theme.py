"""Theme selection handlers."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery

from app.bot.texts import (
    CALLBACK_THEMES,
    THEME_PROMPT,
)
from app.bot.keyboards.themes import build_theme_keyboard

router = Router(name="theme")


@router.callback_query(F.data == CALLBACK_THEMES)
async def open_theme_selection(callback_query: CallbackQuery) -> None:
    """Open theme chooser directly from menu."""
    await callback_query.answer()
    if callback_query.message is not None:
        await callback_query.message.answer(THEME_PROMPT, reply_markup=build_theme_keyboard())
