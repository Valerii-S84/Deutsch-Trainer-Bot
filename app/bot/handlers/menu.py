"""Main menu handlers."""

from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from app.bot.handlers.common import session_factory as _session_factory
from app.bot.handlers.common import extract_user_id as _extract_user_id
from app.bot.handlers.training_message_flow import (
    continue_active_training_from_message,
    start_saved_theme_training_from_message,
)
from app.bot.keyboards.levels import build_levels_keyboard
from app.bot.keyboards.main_menu import build_main_menu_keyboard, build_main_menu_text
from app.bot.keyboards.themes import build_theme_group_keyboard
from app.bot.texts import (
    CALLBACK_CONTINUE,
    CALLBACK_HOME,
    THEME_EMPTY_STATE_TEXT,
    THEME_GROUP_PROMPT,
    TRAINING_PROMPT,
    TRAINING_QUIZBANK_UNAVAILABLE_TEXT,
)
from app.bot.theme_groups import is_known_theme_id
from app.catalog.service import LocalCatalogNotConfiguredError, LocalCatalogQuizService
from app.catalog.selection import CatalogLevelDisabledError
from app.logging_config import log_exception_summary
from app.repositories.users import UserRepository
from app.services.training_session import TrainingSessionService

router = Router(name="menu")
logger = logging.getLogger(__name__)
_training_service = TrainingSessionService()
_catalog_service = LocalCatalogQuizService
_user_repo = UserRepository()


@router.message(Command("menu"))
async def open_menu(message: Message) -> None:
    """Open main menu on explicit /menu request."""
    user = await _load_user(_extract_user_id(message))
    await message.answer(
        build_main_menu_text(
            level=getattr(user, "selected_level", None),
            theme=getattr(user, "selected_theme", None),
        ),
        reply_markup=build_main_menu_keyboard(),
    )


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
        user = await _load_user(_extract_user_id(callback_query))
        await callback_query.message.answer(
            build_main_menu_text(
                level=getattr(user, "selected_level", None),
                theme=getattr(user, "selected_theme", None),
            ),
            reply_markup=build_main_menu_keyboard(),
        )


@router.callback_query(F.data == CALLBACK_CONTINUE)
async def continue_training(callback_query: CallbackQuery) -> None:
    """Continue active training or route to the next configured training step."""
    await callback_query.answer()
    if callback_query.message is None:
        return

    user_id = _extract_user_id(callback_query)
    if user_id is None:
        await callback_query.message.answer(TRAINING_PROMPT, reply_markup=build_levels_keyboard())
        return

    if await continue_active_training_from_message(callback_query.message, user_id):
        return

    user = await _load_user(user_id)
    selected_level = getattr(user, "selected_level", None)
    selected_theme = getattr(user, "selected_theme", None)
    if not selected_level:
        await callback_query.message.answer(TRAINING_PROMPT, reply_markup=build_levels_keyboard())
        return
    if is_known_theme_id(selected_theme):
        await start_saved_theme_training_from_message(
            callback_query.message,
            user_id,
            level=selected_level,
            theme=selected_theme,
        )
        return
    await _open_theme_groups(callback_query, selected_level)


async def _load_user(user_id: int | None):
    if user_id is None:
        return None
    async with _session_factory() as db:
        return await _user_repo.get_by_telegram_id(db, user_id)


async def _open_theme_groups(callback_query: CallbackQuery, selected_level: str) -> None:
    try:
        async with _session_factory() as db:
            themes_response = await _catalog_service().get_themes(db, level=selected_level)
    except (CatalogLevelDisabledError, LocalCatalogNotConfiguredError):
        await callback_query.message.answer(TRAINING_QUIZBANK_UNAVAILABLE_TEXT, reply_markup=build_levels_keyboard())
        return

    if not themes_response.themes:
        await callback_query.message.answer(THEME_EMPTY_STATE_TEXT, reply_markup=build_levels_keyboard())
        return
    await callback_query.message.answer(
        THEME_GROUP_PROMPT.format(level=selected_level),
        reply_markup=build_theme_group_keyboard(selected_level=selected_level, themes=themes_response.themes),
    )
