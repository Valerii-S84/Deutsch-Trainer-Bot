"""Start and onboarding entrypoint handlers."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.types import Message

from app.bot.formatting import escape_markdown_text
from app.bot.keyboards.main_menu import build_main_menu_keyboard
from app.bot.texts import MENU_PROMPT, WELCOME_TEXT
from app.db.session import get_session as _get_session
from app.repositories.users import UserRepository

router = Router(name="start")
_user_repo = UserRepository()


def _session_factory():
    return _get_session()


async def _remember_user(message: Message) -> None:
    if message.from_user is None:
        return

    async with _session_factory() as db:
        try:
            await _user_repo.create_or_update_from_telegram(db, message.from_user)
            await db.commit()
        except Exception:
            # /start should still return the safe menu if persistence is temporarily unavailable.
            await db.rollback()


@router.message(CommandStart())
async def handle_start(message: Message) -> None:
    """Handle /start for both first-time and returning users."""
    await _remember_user(message)
    text = WELCOME_TEXT
    if message.from_user and getattr(message.from_user, "first_name", None):
        first_name = escape_markdown_text(message.from_user.first_name)
        text = f"{text}\n\nHallo *{first_name}*! {MENU_PROMPT}"
    await message.answer(
        text=text,
        reply_markup=build_main_menu_keyboard(),
        parse_mode="Markdown",
    )


@router.message(F.text == "/start")
async def handle_raw_start(message: Message) -> None:
    """Handle raw '/start' text when command parser differs."""
    await handle_start(message)
