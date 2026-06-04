"""Theme selection keyboard built from Quiz Bank availability."""

from __future__ import annotations

from collections.abc import Iterable

from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.bot.texts import (
    CALLBACK_THEME_PREFIX,
    CALLBACK_HOME,
    MENU_BUTTON_HOME,
)


def build_theme_keyboard(selected_level: str | None = None, themes: Iterable[object] | None = None):
    builder = InlineKeyboardBuilder()
    selected_level = (selected_level or "").strip()
    for theme in themes or ():
        theme_text = _theme_text(theme)
        if not theme_text:
            continue
        key = f"{selected_level}:{theme_text}"
        builder.button(
            text=theme_text,
            callback_data=f"{CALLBACK_THEME_PREFIX}{key}",
        )
    builder.button(text=MENU_BUTTON_HOME, callback_data=CALLBACK_HOME)
    builder.adjust(2)
    return builder.as_markup()


def _theme_text(theme: object) -> str:
    raw_value = getattr(theme, "theme", theme)
    return str(raw_value or "").strip()
