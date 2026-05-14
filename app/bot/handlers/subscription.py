"""Subscription entrypoint."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from app.bot.keyboards.main_menu import build_back_to_main_menu_button
from app.bot.texts import CALLBACK_SUBSCRIPTION, SUBSCRIPTION_TEXT

router = Router(name="subscription")


@router.message(Command("subscription"))
async def handle_subscription_message(message: Message) -> None:
    await message.answer(SUBSCRIPTION_TEXT, reply_markup=build_back_to_main_menu_button())


@router.callback_query(F.data == CALLBACK_SUBSCRIPTION)
async def handle_subscription_callback(callback_query: CallbackQuery) -> None:
    await callback_query.answer()
    if callback_query.message is not None:
        await callback_query.message.answer(
            SUBSCRIPTION_TEXT,
            reply_markup=build_back_to_main_menu_button(),
        )
