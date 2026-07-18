"""Start and onboarding entrypoint handlers."""

from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.types import Message

from app.bot.formatting import escape_markdown_text
from app.bot.handlers.common import session_factory as _session_factory
from app.bot.keyboards.levels import build_levels_keyboard
from app.bot.keyboards.main_menu import build_main_menu_keyboard, build_main_menu_text
from app.bot.texts import TRAINING_PROMPT, WELCOME_TEXT
from app.logging_config import log_exception_summary
from app.services.analytics import AnalyticsTracker
from app.repositories.users import UserRepository

router = Router(name="start")
logger = logging.getLogger(__name__)
_user_repo = UserRepository()
_analytics_tracker = AnalyticsTracker()


async def _remember_user(message: Message):
    if message.from_user is None:
        return None

    async with _session_factory() as db:
        try:
            existing = None
            if hasattr(_user_repo, "get_by_telegram_id"):
                existing = await _user_repo.get_by_telegram_id(db, int(message.from_user.id))
            user = await _user_repo.create_or_update_from_telegram(db, message.from_user)
            if user is not None and getattr(user, "id", None) is None and hasattr(db, "flush"):
                await db.flush()
            if user is not None:
                is_first_time_user = existing is None
                internal_user_id = getattr(user, "id", None)
                await _analytics_tracker.record(
                    db,
                    event_name="bot_started",
                    user_id=internal_user_id,
                    event_metadata={"is_first_time_user": is_first_time_user},
                    source="onboarding",
                )
                if is_first_time_user:
                    await _analytics_tracker.record(
                        db,
                        event_name="user_created",
                        user_id=internal_user_id,
                        event_metadata={"is_first_time_user": True},
                        source="onboarding",
                    )
            await db.commit()
            return user
        except Exception as exc:
            # /start should still return a safe onboarding screen if persistence is temporarily unavailable.
            log_exception_summary(
                logger,
                "start_user_persist_failed",
                exc,
                telegram_user_id=message.from_user.id,
            )
            await db.rollback()
    return None


@router.message(CommandStart())
async def handle_start(message: Message) -> None:
    """Handle /start for both first-time and returning users."""
    user = await _remember_user(message)
    if user is None or not getattr(user, "selected_level", None):
        await message.answer(TRAINING_PROMPT, reply_markup=build_levels_keyboard())
        return

    text = WELCOME_TEXT
    if message.from_user and getattr(message.from_user, "first_name", None):
        first_name = escape_markdown_text(message.from_user.first_name)
        text = f"{text}\n\nHallo *{first_name}*!\n\n"
    else:
        text = f"{text}\n\n"
    text = f"{text}{build_main_menu_text(level=user.selected_level, theme=getattr(user, 'selected_theme', None))}"
    await message.answer(
        text=text,
        reply_markup=build_main_menu_keyboard(),
        parse_mode="Markdown",
    )


@router.message(F.text == "/start")
async def handle_raw_start(message: Message) -> None:
    """Handle raw '/start' text when command parser differs."""
    await handle_start(message)
