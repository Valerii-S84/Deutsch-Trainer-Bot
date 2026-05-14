"""Main menu inline keyboard."""

from __future__ import annotations

from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.bot.texts import (
    CALLBACK_HOME,
    CALLBACK_LEVELS,
    CALLBACK_THEMES,
    CALLBACK_PROFILE,
    CALLBACK_SUBSCRIPTION,
    MENU_BUTTON_HOME,
    MENU_BUTTON_LEVEL_THEME,
    MENU_BUTTON_PROGRESS,
    MENU_BUTTON_SUBSCRIPTION,
    MENU_BUTTON_TRAIN,
)


def build_main_menu_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text=MENU_BUTTON_TRAIN, callback_data=CALLBACK_LEVELS)
    builder.button(text=MENU_BUTTON_LEVEL_THEME, callback_data=CALLBACK_THEMES)
    builder.button(text=MENU_BUTTON_PROGRESS, callback_data=CALLBACK_PROFILE)
    builder.button(text=MENU_BUTTON_SUBSCRIPTION, callback_data=CALLBACK_SUBSCRIPTION)
    builder.button(text=MENU_BUTTON_HOME, callback_data=CALLBACK_HOME)
    builder.adjust(1)
    return builder.as_markup()


def build_back_to_main_menu_button():
    builder = InlineKeyboardBuilder()
    builder.button(text=MENU_BUTTON_HOME, callback_data=CALLBACK_HOME)
    return builder.as_markup()
