from __future__ import annotations

from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.bot.texts import (
    CALLBACK_HOME,
    CALLBACK_LEVELS,
    CALLBACK_TRAIN_ANSWER_PREFIX,
    CALLBACK_TRAIN_CANCEL_PREFIX,
    CALLBACK_TRAIN_NEXT_PREFIX,
    CALLBACK_TRAIN_RESUME_PREFIX,
    CALLBACK_TRAIN_NEW_PREFIX,
    MENU_BUTTON_HOME,
    MENU_BUTTON_TRAIN,
    TRAINING_NEW_SESSION_BUTTON_TEXT,
    TRAINING_NEXT_BUTTON_TEXT,
)
from app.services.training_session import QuizQuestionPayload


def build_question_options_keyboard(
    question: QuizQuestionPayload,
) -> InlineKeyboardBuilder:
    builder = InlineKeyboardBuilder()
    for option_id, option_text in question.answer_options:
        builder.button(
            text=option_text,
            callback_data=f"{CALLBACK_TRAIN_ANSWER_PREFIX}:{question.session_id}:{question.question_token}:{option_id}",
        )
    builder.button(text=MENU_BUTTON_HOME, callback_data=CALLBACK_HOME)
    builder.adjust(1)
    return builder.as_markup()


def build_next_question_keyboard(session_id: int, question_token: str):
    builder = InlineKeyboardBuilder()
    builder.button(
        text=TRAINING_NEXT_BUTTON_TEXT,
        callback_data=f"{CALLBACK_TRAIN_NEXT_PREFIX}:{session_id}:{question_token}",
    )
    builder.button(text=MENU_BUTTON_HOME, callback_data=CALLBACK_HOME)
    builder.adjust(1)
    return builder.as_markup()


def build_finish_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text=MENU_BUTTON_HOME, callback_data=CALLBACK_HOME)
    builder.button(text=TRAINING_NEW_SESSION_BUTTON_TEXT, callback_data=CALLBACK_LEVELS)
    builder.adjust(1)
    return builder.as_markup()


def build_resume_keyboard(session_id: int):
    builder = InlineKeyboardBuilder()
    builder.button(text="▶️ Fortsetzen", callback_data=f"{CALLBACK_TRAIN_RESUME_PREFIX}:{session_id}")
    builder.button(
        text="🆕 Neue Runde",
        callback_data=f"{CALLBACK_TRAIN_NEW_PREFIX}:{session_id}",
    )
    builder.button(text="🛑 Sitzung abbrechen", callback_data=f"{CALLBACK_TRAIN_CANCEL_PREFIX}:{session_id}")
    builder.button(text=MENU_BUTTON_HOME, callback_data=CALLBACK_HOME)
    builder.adjust(1)
    return builder.as_markup()
