"""Profile / progress entrypoint."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from app.bot.keyboards.main_menu import build_back_to_main_menu_button
from app.bot.texts import CALLBACK_PROFILE, PROFILE_TEXT

router = Router(name="profile")


@router.message(Command("profile"))
async def handle_profile_message(message: Message) -> None:
    await message.answer(PROFILE_TEXT, reply_markup=build_back_to_main_menu_button())


@router.callback_query(F.data == CALLBACK_PROFILE)
async def handle_profile_callback(callback_query: CallbackQuery) -> None:
    await callback_query.answer()
    if callback_query.message is not None:
        await callback_query.message.answer(
            PROFILE_TEXT,
            reply_markup=build_back_to_main_menu_button(),
        )
