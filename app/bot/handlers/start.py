"""Start and onboarding entrypoint handlers."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.types import Message

from app.bot.keyboards.main_menu import build_main_menu_keyboard
from app.bot.texts import MENU_PROMPT, WELCOME_TEXT

router = Router(name="start")


@router.message(CommandStart())
async def handle_start(message: Message) -> None:
    """Handle /start for both first-time and returning users."""
    text = WELCOME_TEXT
    if message.from_user and getattr(message.from_user, "first_name", None):
        text = f"{text}\n\nHallo *{message.from_user.first_name}*! {MENU_PROMPT}"
    await message.answer(
        text=text,
        reply_markup=build_main_menu_keyboard(),
        parse_mode="Markdown",
    )


@router.message(F.text == "/start")
async def handle_raw_start(message: Message) -> None:
    """Handle raw '/start' text when command parser differs."""
    await handle_start(message)
