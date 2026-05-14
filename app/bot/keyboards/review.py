"""Keyboard helpers for mistake review flow."""

from __future__ import annotations

from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.bot.texts import CALLBACK_HOME, MENU_BUTTON_HOME


def build_review_empty_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text=MENU_BUTTON_HOME, callback_data=CALLBACK_HOME)
    return builder.as_markup()

