"""Keyboard helpers for mistake review flow."""

from __future__ import annotations

from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.bot.texts import (
    CALLBACK_HOME,
    CALLBACK_PROFILE,
    CALLBACK_REVIEW_START,
    MENU_BUTTON_HOME,
    MENU_BUTTON_PROGRESS,
    MENU_BUTTON_REVIEW_START,
)


def build_review_screen_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text=MENU_BUTTON_REVIEW_START, callback_data=CALLBACK_REVIEW_START)
    builder.button(text=MENU_BUTTON_PROGRESS, callback_data=CALLBACK_PROFILE)
    builder.button(text=MENU_BUTTON_HOME, callback_data=CALLBACK_HOME)
    builder.adjust(1)
    return builder.as_markup()


def build_review_empty_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text=MENU_BUTTON_HOME, callback_data=CALLBACK_HOME)
    return builder.as_markup()
