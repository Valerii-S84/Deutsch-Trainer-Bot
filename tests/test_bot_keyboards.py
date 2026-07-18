from __future__ import annotations

from types import SimpleNamespace

from app.bot.keyboards.main_menu import build_main_menu_keyboard
from app.bot.keyboards.levels import build_levels_keyboard
from app.bot.keyboards.themes import build_theme_group_keyboard, build_theme_keyboard
from app.bot.theme_groups import THEME_GROUPS
from app.bot.texts import (
    MENU_BUTTON_CHANGE_LEVEL,
    MENU_BUTTON_CHOOSE_THEME,
    MENU_BUTTON_CONTINUE,
    MENU_BUTTON_HOME,
    MENU_BUTTON_PROGRESS,
)


def _button_texts(keyboard) -> list[str]:
    return [button.text for row in keyboard.inline_keyboard for button in row]


def _button_payloads(keyboard) -> list[str]:
    return [button.callback_data for row in keyboard.inline_keyboard for button in row]


def test_main_menu_keyboard_contains_required_actions() -> None:
    keyboard = build_main_menu_keyboard()
    texts = _button_texts(keyboard)
    payloads = _button_payloads(keyboard)

    assert MENU_BUTTON_CONTINUE in texts
    assert MENU_BUTTON_CHOOSE_THEME in texts
    assert MENU_BUTTON_PROGRESS in texts
    assert MENU_BUTTON_HOME not in texts
    assert payloads == ["menu:continue", "menu:themes", "menu:profile"]


def test_levels_keyboard_is_complete() -> None:
    keyboard = build_levels_keyboard()
    texts = _button_texts(keyboard)
    assert texts[:5] == ["A1", "A2", "B1", "B2", "C1"]


def test_theme_groups_cover_all_canonical_theme_ids_once() -> None:
    theme_ids = [theme_id for group in THEME_GROUPS for theme_id in group.theme_ids]

    assert len(THEME_GROUPS) == 6
    assert sorted(theme_ids) == [f"T{index:02d}" for index in range(1, 19)]
    assert len(theme_ids) == len(set(theme_ids)) == 18


def test_theme_group_keyboard_only_shows_groups_with_available_themes() -> None:
    themes = [
        _theme("Person / Identität / Familie", "T01", count=3),
        _theme("Beruf", "T07", count=2),
        _theme("Umwelt", "T17", count=0),
    ]
    keyboard = build_theme_group_keyboard(selected_level="A1", themes=themes)
    payloads = _button_payloads(keyboard)

    assert payloads == ["group:A1:G01", "group:A1:G03", "menu:levels", "bot:home"]


def test_theme_keyboard_uses_stable_theme_ids() -> None:
    themes = [
        _theme("Person / Identität / Familie", "T01", count=3),
        _theme("Einkaufen", "T04", count=0),
        _theme("Alltag", "T05", count=2),
    ]
    keyboard = build_theme_keyboard(selected_level="A1", themes=themes, group_id="G01")
    texts = _button_texts(keyboard)
    payloads = _button_payloads(keyboard)

    assert texts[:2] == ["Person / Identität / Familie", "Alltag"]
    assert payloads == ["theme:A1:T01", "theme:A1:T05", "groups:A1", "menu:levels", "bot:home"]
    assert all(len(payload.encode("utf-8")) <= 64 for payload in payloads)
    assert MENU_BUTTON_CHANGE_LEVEL in texts


def _theme(name: str, theme_key: str, *, count: int) -> SimpleNamespace:
    return SimpleNamespace(theme=name, theme_key=theme_key, available_items_count=count)
