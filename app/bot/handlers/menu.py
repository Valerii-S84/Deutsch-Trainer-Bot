"""Main menu handlers."""

from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from app.bot.handlers.common import session_factory as _session_factory
from app.bot.keyboards.main_menu import build_main_menu_keyboard
from app.bot.texts import CALLBACK_HOME, HOME_TEXT, MENU_PROMPT
from app.logging_config import log_exception_summary
from app.services.training_session import TrainingSessionService

router = Router(name="menu")
logger = logging.getLogger(__name__)
_training_service = TrainingSessionService()


@router.message(Command("menu"))
async def open_menu(message: Message) -> None:
    """Open main menu on explicit /menu request."""
    await message.answer(f"{MENU_PROMPT}\n\n{HOME_TEXT}", reply_markup=build_main_menu_keyboard())


async def _abandon_active_training(callback_query: CallbackQuery) -> None:
    if callback_query.from_user is None:
        return

    async with _session_factory() as db:
        try:
            await _training_service.cancel_active_session(db, callback_query.from_user.id)
            await db.commit()
        except Exception as exc:
            # Home must remain a safe escape hatch even if persistence is unavailable.
            log_exception_summary(
                logger,
                "home_abandon_active_training_failed",
                exc,
                telegram_user_id=callback_query.from_user.id,
            )
            await db.rollback()


@router.callback_query(F.data == CALLBACK_HOME)
async def open_menu_from_callback(callback_query: CallbackQuery) -> None:
    """Return to the main menu from any flow."""
    await callback_query.answer()
    await _abandon_active_training(callback_query)
    if callback_query.message is not None:
        await callback_query.message.answer(
            f"{MENU_PROMPT}\n\n{HOME_TEXT}",
            reply_markup=build_main_menu_keyboard(),
        )
