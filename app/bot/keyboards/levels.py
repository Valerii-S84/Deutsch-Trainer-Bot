"""Level selection keyboard."""

from __future__ import annotations

from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.bot.texts import CALLBACK_LEVEL_PREFIX, LEVELS, MENU_BUTTON_HOME
from app.bot.texts import CALLBACK_HOME


def build_levels_keyboard():
    builder = InlineKeyboardBuilder()
    for level in LEVELS:
        builder.button(text=level, callback_data=f"{CALLBACK_LEVEL_PREFIX}{level}")
    builder.button(text=MENU_BUTTON_HOME, callback_data=CALLBACK_HOME)
    builder.adjust(2)
    return builder.as_markup()
