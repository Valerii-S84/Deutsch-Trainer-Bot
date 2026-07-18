"""Main menu inline keyboard."""

from __future__ import annotations

from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.bot.texts import (
    CALLBACK_CONTINUE,
    CALLBACK_HOME,
    CALLBACK_PROFILE,
    CALLBACK_REVIEW,
    CALLBACK_THEMES,
    MENU_BUTTON_CHOOSE_THEME,
    MENU_BUTTON_CONTINUE,
    MENU_BUTTON_HOME,
    MENU_BUTTON_REVIEW,
    MENU_BUTTON_PROGRESS,
    MENU_LEVEL_EMPTY_TEXT,
    MENU_LEVEL_SELECTED_TEXT,
    MENU_PROMPT,
    MENU_THEME_EMPTY_TEXT,
    MENU_THEME_SELECTED_TEXT,
    MENU_TITLE_TEXT,
)


def build_main_menu_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text=MENU_BUTTON_CONTINUE, callback_data=CALLBACK_CONTINUE)
    builder.button(text=MENU_BUTTON_CHOOSE_THEME, callback_data=CALLBACK_THEMES)
    builder.button(text=MENU_BUTTON_PROGRESS, callback_data=CALLBACK_PROFILE)
    builder.adjust(1)
    return builder.as_markup()


def build_back_to_main_menu_button():
    builder = InlineKeyboardBuilder()
    builder.button(text=MENU_BUTTON_HOME, callback_data=CALLBACK_HOME)
    return builder.as_markup()


def build_progress_navigation_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text=MENU_BUTTON_CONTINUE, callback_data=CALLBACK_CONTINUE)
    builder.button(text=MENU_BUTTON_REVIEW, callback_data=CALLBACK_REVIEW)
    builder.button(text=MENU_BUTTON_CHOOSE_THEME, callback_data=CALLBACK_THEMES)
    builder.button(text=MENU_BUTTON_HOME, callback_data=CALLBACK_HOME)
    builder.adjust(1)
    return builder.as_markup()


def build_main_menu_text(*, level: str | None = None, theme: str | None = None) -> str:
    level_line = MENU_LEVEL_SELECTED_TEXT.format(level=level) if level else MENU_LEVEL_EMPTY_TEXT
    theme_line = MENU_THEME_SELECTED_TEXT.format(theme=theme) if theme else MENU_THEME_EMPTY_TEXT
    return f"{MENU_TITLE_TEXT}\n{level_line}\n{theme_line}\n\n{MENU_PROMPT}"
