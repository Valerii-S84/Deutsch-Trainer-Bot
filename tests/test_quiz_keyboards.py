from __future__ import annotations

from app.bot.keyboards.levels import build_levels_keyboard
from app.bot.keyboards.quiz import (
    build_finish_keyboard,
    build_next_question_keyboard,
    build_question_options_keyboard,
    build_resume_keyboard,
)
from app.bot.texts import (
    CALLBACK_TRAIN_ANSWER_PREFIX,
    CALLBACK_TRAIN_CANCEL_PREFIX,
    CALLBACK_TRAIN_NEW_PREFIX,
    CALLBACK_TRAIN_NEXT_PREFIX,
    CALLBACK_TRAIN_RESUME_PREFIX,
    MENU_BUTTON_HOME,
    MENU_BUTTON_TRAIN,
    TRAINING_NEW_SESSION_BUTTON_TEXT,
)
from app.services.training_session import QuizQuestionPayload


def _texts(markup):
    return [button.text for row in markup.inline_keyboard for button in row]


def _payloads(markup):
    return [button.callback_data for row in markup.inline_keyboard for button in row]


def test_question_options_keyboard_callback_data_is_short_and_safe() -> None:
    question = QuizQuestionPayload(
        session_id=12,
        question_token="qtoken",
        question_id="question-id-that-is-long",
        question_text="Was ist die richtige Form von X?",
        answer_options=(("a1", "a"), ("a2", "b"), ("a3", "c")),
        correct_answer="a2",
        explanation=None,
        position=1,
        total_questions=5,
        level="A1",
        theme="Alltag",
    )

    keyboard = build_question_options_keyboard(question)
    payloads = _payloads(keyboard)

    assert len(payloads) == 4
    assert all(not p.startswith(question.question_text) for p in payloads)
    assert all(len(p) < 100 for p in payloads)
    assert all(
        p.startswith(f"{CALLBACK_TRAIN_ANSWER_PREFIX}:") for p in payloads[:-1]
    )
    assert payloads[-1] == "bot:home"


def test_next_question_keyboard_contains_only_next_and_home() -> None:
    keyboard = build_next_question_keyboard(session_id=9, question_token="qtoken")
    texts = _texts(keyboard)
    payloads = _payloads(keyboard)

    assert texts == ["➡️ Nächste Frage", MENU_BUTTON_HOME]
    assert payloads[0].startswith(f"{CALLBACK_TRAIN_NEXT_PREFIX}:9:qtoken")
    assert payloads[1] == "bot:home"


def test_finish_keyboard_shows_menu_and_new_training_action() -> None:
    keyboard = build_finish_keyboard()
    texts = _texts(keyboard)
    payloads = _payloads(keyboard)

    assert MENU_BUTTON_HOME in texts
    assert TRAINING_NEW_SESSION_BUTTON_TEXT in texts
    assert payloads == ["bot:home", "menu:levels"]


def test_resume_keyboard_payloads_are_short() -> None:
    keyboard = build_resume_keyboard(session_id=9)
    payloads = _payloads(keyboard)
    texts = _texts(keyboard)

    assert texts[0] == "▶️ Fortsetzen"
    assert payloads[0] == f"{CALLBACK_TRAIN_RESUME_PREFIX}:9"
    assert payloads[1] == f"{CALLBACK_TRAIN_NEW_PREFIX}:9"
    assert payloads[2] == f"{CALLBACK_TRAIN_CANCEL_PREFIX}:9"
    assert payloads[3] == "bot:home"
    assert MENU_BUTTON_TRAIN not in texts
    assert len(payloads[0]) < 50
    assert len(payloads[1]) < 50
    assert len(payloads[2]) < 50
