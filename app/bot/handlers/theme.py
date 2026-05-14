"""Theme selection handlers."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery

from app.bot.texts import (
    CALLBACK_THEME_PREFIX,
    CALLBACK_THEMES,
    THEME_CALLBACK_FALLBACK_TEXT,
    THEME_PROMPT,
    THEME_SELECTED_TEXT,
    THEMES,
)
from app.bot.keyboards.themes import build_theme_keyboard

router = Router(name="theme")


@router.callback_query(F.data == CALLBACK_THEMES)
async def open_theme_selection(callback_query: CallbackQuery) -> None:
    """Open theme chooser directly from menu."""
    await callback_query.answer()
    if callback_query.message is not None:
        await callback_query.message.answer(THEME_PROMPT, reply_markup=build_theme_keyboard())


@router.callback_query(F.data.startswith(CALLBACK_THEME_PREFIX))
async def theme_selected(callback_query: CallbackQuery) -> None:
    """Show placeholder confirmation for a selected theme."""
    await callback_query.answer()
    theme = (callback_query.data or "").replace(CALLBACK_THEME_PREFIX, "", 1)
    if theme not in {name.lower() for name in THEMES}:
        if callback_query.message is not None:
            await callback_query.message.answer(THEME_CALLBACK_FALLBACK_TEXT)
        return

    if callback_query.message is not None:
        await callback_query.message.answer(
            THEME_SELECTED_TEXT.format(theme=theme.title()),
            parse_mode="Markdown",
            reply_markup=build_theme_keyboard(),
        )
