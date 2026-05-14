from __future__ import annotations

from app.bot.keyboards.main_menu import build_main_menu_keyboard
from app.bot.keyboards.levels import build_levels_keyboard
from app.bot.keyboards.themes import build_theme_keyboard
from app.bot.texts import (
    MENU_BUTTON_HOME,
    MENU_BUTTON_REVIEW,
    MENU_BUTTON_LEVEL_THEME,
    MENU_BUTTON_PROGRESS,
    MENU_BUTTON_SUBSCRIPTION,
    MENU_BUTTON_TRAIN,
    THEMES,
)


def _button_texts(keyboard) -> list[str]:
    return [button.text for row in keyboard.inline_keyboard for button in row]


def _button_payloads(keyboard) -> list[str]:
    return [button.callback_data for row in keyboard.inline_keyboard for button in row]


def test_main_menu_keyboard_contains_required_actions() -> None:
    keyboard = build_main_menu_keyboard()
    texts = _button_texts(keyboard)
    payloads = _button_payloads(keyboard)

    assert MENU_BUTTON_TRAIN in texts
    assert MENU_BUTTON_LEVEL_THEME in texts
    assert MENU_BUTTON_REVIEW in texts
    assert MENU_BUTTON_PROGRESS in texts
    assert MENU_BUTTON_SUBSCRIPTION in texts
    assert MENU_BUTTON_HOME in texts
    assert len(payloads) == 6
    assert len(payloads) >= len(set(payloads)) >= 4


def test_levels_keyboard_is_complete() -> None:
    keyboard = build_levels_keyboard()
    texts = _button_texts(keyboard)
    assert texts[:6] == ["A1", "A2", "B1", "B2", "C1", "C2"]


def test_theme_keyboard_uses_placeholder_categories() -> None:
    keyboard = build_theme_keyboard()
    texts = _button_texts(keyboard)
    for theme in THEMES:
        assert theme in texts
