"""Theme selection keyboard (placeholder list, not final curriculum)."""

from __future__ import annotations

from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.bot.texts import (
    CALLBACK_THEME_PREFIX,
    CALLBACK_HOME,
    MENU_BUTTON_HOME,
    THEMES,
)


def build_theme_keyboard():
    builder = InlineKeyboardBuilder()
    for theme in THEMES:
        builder.button(text=theme, callback_data=f"{CALLBACK_THEME_PREFIX}{theme.lower()}")
    builder.button(text=MENU_BUTTON_HOME, callback_data=CALLBACK_HOME)
    builder.adjust(2)
    return builder.as_markup()
