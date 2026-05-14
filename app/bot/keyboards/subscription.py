from __future__ import annotations

from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.bot.texts import (
    CALLBACK_HOME,
    CALLBACK_PROFILE,
    CALLBACK_SUBSCRIPTION,
    MENU_BUTTON_HOME,
    MENU_BUTTON_PROGRESS,
    PAYWALL_PLUS_BUTTON_TEXT,
)


def build_subscription_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text=MENU_BUTTON_HOME, callback_data=CALLBACK_HOME)
    builder.adjust(1)
    return builder.as_markup()


def build_paywall_keyboard(*, include_progress: bool = False):
    builder = InlineKeyboardBuilder()
    builder.button(text=PAYWALL_PLUS_BUTTON_TEXT, callback_data=CALLBACK_SUBSCRIPTION)
    if include_progress:
        builder.button(text=MENU_BUTTON_PROGRESS, callback_data=CALLBACK_PROFILE)
    builder.button(text=MENU_BUTTON_HOME, callback_data=CALLBACK_HOME)
    builder.adjust(1)
    return builder.as_markup()
