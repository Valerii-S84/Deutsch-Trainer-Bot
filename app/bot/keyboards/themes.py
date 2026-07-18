"""Theme selection keyboards built from local catalog availability."""

from __future__ import annotations

from collections.abc import Iterable

from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.bot.theme_groups import THEME_GROUPS, ThemeGroup, get_theme_group
from app.bot.texts import (
    CALLBACK_GROUP_PREFIX,
    CALLBACK_GROUPS_PREFIX,
    CALLBACK_THEME_PREFIX,
    CALLBACK_HOME,
    CALLBACK_LEVELS,
    MENU_BUTTON_BACK_TO_GROUPS,
    MENU_BUTTON_CHANGE_LEVEL,
    MENU_BUTTON_HOME,
)


def build_theme_group_keyboard(selected_level: str | None = None, themes: Iterable[object] | None = None):
    builder = InlineKeyboardBuilder()
    selected_level = (selected_level or "").strip()
    available_ids = _available_theme_ids(themes)
    for group in THEME_GROUPS:
        if not any(theme_id in available_ids for theme_id in group.theme_ids):
            continue
        builder.button(
            text=group.label,
            callback_data=f"{CALLBACK_GROUP_PREFIX}{selected_level}:{group.group_id}",
        )
    builder.button(text=MENU_BUTTON_CHANGE_LEVEL, callback_data=CALLBACK_LEVELS)
    builder.button(text=MENU_BUTTON_HOME, callback_data=CALLBACK_HOME)
    builder.adjust(2)
    return builder.as_markup()


def build_theme_keyboard(
    selected_level: str | None = None,
    themes: Iterable[object] | None = None,
    *,
    group_id: str | None = None,
):
    builder = InlineKeyboardBuilder()
    selected_level = (selected_level or "").strip()
    group = get_theme_group(group_id)
    for theme in _available_themes(themes, group=group):
        theme_text = _theme_text(theme)
        theme_id = _theme_id(theme)
        if not theme_text or not theme_id:
            continue
        builder.button(
            text=theme_text,
            callback_data=f"{CALLBACK_THEME_PREFIX}{selected_level}:{theme_id}",
        )
    if group is not None:
        builder.button(text=MENU_BUTTON_BACK_TO_GROUPS, callback_data=f"{CALLBACK_GROUPS_PREFIX}{selected_level}")
    builder.button(text=MENU_BUTTON_CHANGE_LEVEL, callback_data=CALLBACK_LEVELS)
    builder.button(text=MENU_BUTTON_HOME, callback_data=CALLBACK_HOME)
    builder.adjust(1)
    return builder.as_markup()


def _available_themes(themes: Iterable[object] | None, *, group: ThemeGroup | None = None) -> tuple[object, ...]:
    available = tuple(theme for theme in themes or () if _is_available(theme))
    if group is None:
        return available
    group_theme_ids = set(group.theme_ids)
    return tuple(theme for theme in available if _theme_id(theme) in group_theme_ids)


def _available_theme_ids(themes: Iterable[object] | None) -> set[str]:
    return {theme_id for theme in themes or () if _is_available(theme) and (theme_id := _theme_id(theme))}


def _is_available(theme: object) -> bool:
    item_count = getattr(theme, "available_items_count", getattr(theme, "item_count", 1))
    return int(item_count or 0) > 0


def _theme_id(theme: object) -> str:
    raw_value = getattr(theme, "theme_key", None) or getattr(theme, "theme_id", None)
    return str(raw_value or "").strip().upper()


def _theme_text(theme: object) -> str:
    raw_value = getattr(theme, "theme", theme)
    return str(raw_value or "").strip()
