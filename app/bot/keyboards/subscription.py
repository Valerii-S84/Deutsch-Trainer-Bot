from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.bot.texts import (
    CALLBACK_HOME,
    CALLBACK_LEVELS,
    CALLBACK_PAYMENT_PLAN_PREFIX,
    CALLBACK_PROFILE,
    CALLBACK_REVIEW,
    CALLBACK_SUBSCRIPTION,
    MENU_BUTTON_HOME,
    MENU_BUTTON_PROGRESS,
    MENU_BUTTON_REVIEW,
    MENU_BUTTON_TRAIN,
    PAYMENT_INVOICE_PAY_BUTTON_TEXT,
    PAYMENT_PLUS_BUTTON_TEXT,
    PAYMENT_PRO_BUTTON_TEXT,
    PAYMENT_RETRY_BUTTON_TEXT,
    PAYWALL_PLUS_BUTTON_TEXT,
)


def build_subscription_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text=PAYMENT_PLUS_BUTTON_TEXT, callback_data=f"{CALLBACK_PAYMENT_PLAN_PREFIX}plus")
    builder.button(text=PAYMENT_PRO_BUTTON_TEXT, callback_data=f"{CALLBACK_PAYMENT_PLAN_PREFIX}pro")
    builder.button(text=MENU_BUTTON_HOME, callback_data=CALLBACK_HOME)
    builder.adjust(1)
    return builder.as_markup()


def build_invoice_payment_keyboard(*, amount_stars: int):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=PAYMENT_INVOICE_PAY_BUTTON_TEXT.format(amount_stars=amount_stars),
                    pay=True,
                ),
            ],
        ],
    )


def build_paywall_keyboard(*, include_progress: bool = False):
    builder = InlineKeyboardBuilder()
    builder.button(text=PAYWALL_PLUS_BUTTON_TEXT, callback_data=CALLBACK_SUBSCRIPTION)
    if include_progress:
        builder.button(text=MENU_BUTTON_PROGRESS, callback_data=CALLBACK_PROFILE)
    builder.button(text=MENU_BUTTON_HOME, callback_data=CALLBACK_HOME)
    builder.adjust(1)
    return builder.as_markup()


def build_payment_success_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text=MENU_BUTTON_TRAIN, callback_data=CALLBACK_LEVELS)
    builder.button(text=MENU_BUTTON_PROGRESS, callback_data=CALLBACK_PROFILE)
    builder.button(text=MENU_BUTTON_REVIEW, callback_data=CALLBACK_REVIEW)
    builder.adjust(1)
    return builder.as_markup()


def build_payment_failure_keyboard(*, plan: str = "plus"):
    builder = InlineKeyboardBuilder()
    builder.button(text=PAYMENT_RETRY_BUTTON_TEXT, callback_data=f"{CALLBACK_PAYMENT_PLAN_PREFIX}{plan}")
    builder.button(text=MENU_BUTTON_HOME, callback_data=CALLBACK_HOME)
    builder.adjust(1)
    return builder.as_markup()
