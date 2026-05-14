"""Main menu handlers."""

from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from aiogram import F

from app.bot.keyboards.main_menu import build_main_menu_keyboard
from app.bot.texts import CALLBACK_HOME, HOME_TEXT, MENU_PROMPT

router = Router(name="menu")


@router.message(Command("menu"))
async def open_menu(message: Message) -> None:
    """Open main menu on explicit /menu request."""
    await message.answer(f"{MENU_PROMPT}\n\n{HOME_TEXT}", reply_markup=build_main_menu_keyboard())


@router.callback_query(F.data == CALLBACK_HOME)
async def open_menu_from_callback(callback_query: CallbackQuery) -> None:
    """Return to the main menu from any flow."""
    await callback_query.answer()
    if callback_query.message is not None:
        await callback_query.message.answer(
            f"{MENU_PROMPT}\n\n{HOME_TEXT}",
            reply_markup=build_main_menu_keyboard(),
        )
