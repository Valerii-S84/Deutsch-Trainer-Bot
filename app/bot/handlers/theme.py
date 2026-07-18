"""Theme selection handlers."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery

from app.bot.keyboards.levels import build_levels_keyboard
from app.bot.keyboards.themes import build_theme_group_keyboard, build_theme_keyboard
from app.bot.theme_groups import get_theme_group
from app.bot.texts import (
    CALLBACK_GROUP_PREFIX,
    CALLBACK_GROUPS_PREFIX,
    CALLBACK_THEMES,
    LEVELS,
    THEME_EMPTY_STATE_TEXT,
    THEME_GROUP_PROMPT,
    THEME_PROMPT,
    THEME_CALLBACK_FALLBACK_TEXT,
    TRAINING_NO_LEVEL_SELECTED_TEXT,
    TRAINING_QUIZBANK_UNAVAILABLE_TEXT,
)
from app.bot.handlers.common import extract_user_id as _extract_user_id
from app.bot.handlers.common import session_factory as _session_factory
from app.catalog.service import LocalCatalogNotConfiguredError, LocalCatalogQuizService
from app.catalog.selection import CatalogLevelDisabledError
from app.repositories.users import UserRepository

router = Router(name="theme")
_catalog_service = LocalCatalogQuizService
_user_repo = UserRepository()


@router.callback_query(F.data == CALLBACK_THEMES)
async def open_theme_selection(callback_query: CallbackQuery) -> None:
    """Open theme chooser directly from menu."""
    await callback_query.answer()
    user_id = _extract_user_id(callback_query)
    if user_id is None:
        if callback_query.message is not None:
            await callback_query.message.answer(TRAINING_NO_LEVEL_SELECTED_TEXT, reply_markup=build_levels_keyboard())
        return

    async with _session_factory() as db:
        user = await _user_repo.get_by_telegram_id(db, user_id)

    selected_level = getattr(user, "selected_level", None)
    if not selected_level:
        if callback_query.message is not None:
            await callback_query.message.answer(TRAINING_NO_LEVEL_SELECTED_TEXT, reply_markup=build_levels_keyboard())
        return

    try:
        async with _session_factory() as db:
            themes_response = await _catalog_service().get_themes(db, level=selected_level)
    except (CatalogLevelDisabledError, LocalCatalogNotConfiguredError):
        if callback_query.message is not None:
            await callback_query.message.answer(
                TRAINING_QUIZBANK_UNAVAILABLE_TEXT,
                reply_markup=build_levels_keyboard(),
            )
        return

    if callback_query.message is not None:
        if not themes_response.themes:
            await callback_query.message.answer(THEME_EMPTY_STATE_TEXT, reply_markup=build_levels_keyboard())
            return
        await callback_query.message.answer(
            THEME_GROUP_PROMPT.format(level=selected_level),
            reply_markup=build_theme_group_keyboard(selected_level=selected_level, themes=themes_response.themes),
        )


@router.callback_query(F.data.startswith(CALLBACK_GROUPS_PREFIX))
async def open_theme_groups_for_level(callback_query: CallbackQuery) -> None:
    """Return from a group to the available theme groups for a level."""
    await callback_query.answer()
    selected_level = (callback_query.data or "").removeprefix(CALLBACK_GROUPS_PREFIX).strip()
    if selected_level not in LEVELS:
        if callback_query.message is not None:
            await callback_query.message.answer(TRAINING_NO_LEVEL_SELECTED_TEXT, reply_markup=build_levels_keyboard())
        return

    themes_response = await _load_themes(callback_query, selected_level)
    if themes_response is None or callback_query.message is None:
        return
    if not themes_response.themes:
        await callback_query.message.answer(THEME_EMPTY_STATE_TEXT, reply_markup=build_levels_keyboard())
        return
    await callback_query.message.answer(
        THEME_GROUP_PROMPT.format(level=selected_level),
        reply_markup=build_theme_group_keyboard(selected_level=selected_level, themes=themes_response.themes),
    )


@router.callback_query(F.data.startswith(CALLBACK_GROUP_PREFIX))
async def open_theme_group(callback_query: CallbackQuery) -> None:
    """Open the available themes inside a selected group."""
    await callback_query.answer()
    try:
        selected_level, group_id = _parse_group_payload(callback_query.data)
    except ValueError:
        if callback_query.message is not None:
            await callback_query.message.answer(THEME_CALLBACK_FALLBACK_TEXT)
        return

    group = get_theme_group(group_id)
    themes_response = await _load_themes(callback_query, selected_level)
    if group is None or themes_response is None or callback_query.message is None:
        return

    keyboard = build_theme_keyboard(selected_level=selected_level, themes=themes_response.themes, group_id=group.group_id)
    if not keyboard.inline_keyboard or len(keyboard.inline_keyboard) <= 3:
        await callback_query.message.answer(THEME_EMPTY_STATE_TEXT, reply_markup=build_theme_group_keyboard(selected_level, themes_response.themes))
        return
    await callback_query.message.answer(
        THEME_PROMPT.format(level=selected_level, group=group.label),
        reply_markup=keyboard,
    )


async def _load_themes(callback_query: CallbackQuery, selected_level: str):
    try:
        async with _session_factory() as db:
            return await _catalog_service().get_themes(db, level=selected_level)
    except (CatalogLevelDisabledError, LocalCatalogNotConfiguredError):
        if callback_query.message is not None:
            await callback_query.message.answer(
                TRAINING_QUIZBANK_UNAVAILABLE_TEXT,
                reply_markup=build_levels_keyboard(),
            )
        return None


def _parse_group_payload(data: str | None) -> tuple[str, str]:
    if not data or not data.startswith(CALLBACK_GROUP_PREFIX):
        raise ValueError("invalid payload")
    payload = data.removeprefix(CALLBACK_GROUP_PREFIX)
    level, separator, group_id = payload.partition(":")
    if separator != ":" or level not in LEVELS or get_theme_group(group_id) is None:
        raise ValueError("invalid payload")
    return level, group_id
