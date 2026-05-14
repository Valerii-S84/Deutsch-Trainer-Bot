from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.bot.keyboards.levels import build_levels_keyboard
from app.bot.keyboards.quiz import build_resume_keyboard
from app.bot.texts import (
    TRAINING_ANSWER_DUPLICATE_TEXT,
    TRAINING_EXPLANATION_TEXT,
    TRAINING_FINISH_TEXT,
    TRAINING_NO_LEVEL_SELECTED_TEXT,
    TRAINING_NEW_SESSION_BUTTON_TEXT,
    TRAINING_NEXT_BUTTON_TEXT,
    TRAINING_QUESTION_TEMPLATE,
    TRAINING_SESSION_RESUME_TEXT,
)
from app.services.training_session import AnswerResult, QuizQuestionPayload

from app.bot.handlers import training


class FakeDb:
    def __init__(self) -> None:
        self.committed = 0
        self.rolled_back = 0

    async def commit(self) -> None:
        self.committed += 1

    async def rollback(self) -> None:
        self.rolled_back += 1


class FakeSessionContext:
    def __init__(self, db: FakeDb) -> None:
        self.db = db

    async def __aenter__(self) -> FakeDb:
        return self.db

    async def __aexit__(self, exc_type, exc, tb) -> None:  # type: ignore[override]
        return None


class _Message:
    def __init__(self, from_user_id: int = 111) -> None:
        self.from_user = SimpleNamespace(id=from_user_id)
        self.answer = AsyncMock()


class _Callback:
    def __init__(self, data: str | None = None, from_user_id: int = 111) -> None:
        self.data = data
        self.message = _Message(from_user_id)
        self.from_user = self.message.from_user
        self.answer = AsyncMock()


def _question() -> QuizQuestionPayload:
    return QuizQuestionPayload(
        session_id=10,
        question_token="tok12345",
        question_id="q1",
        question_text="Was ist korrekt?",
        answer_options=(("a", "Option A"), ("b", "Option B")),
        correct_answer="a",
        explanation="Korrekt, denn ...",
        position=1,
        total_questions=3,
        level="A1",
        theme="Alltag",
    )


def _button_payloads(markup) -> list[str]:
    return [button.callback_data for row in markup.inline_keyboard for button in row]


def _patch_service(monkeypatch, service, db: FakeDb) -> None:
    monkeypatch.setattr(training, "training_service", service)
    monkeypatch.setattr(training, "_session_factory", lambda: FakeSessionContext(db))


def _extract_text(call) -> str:
    if call is None:
        return ""
    return call.args[0]


def _callback_payloads(markup) -> list[str]:
    return [button.callback_data for row in markup.inline_keyboard for button in row]


@pytest.mark.asyncio
async def test_handle_theme_selected_starts_session_and_shows_question(monkeypatch) -> None:
    db = FakeDb()
    service = AsyncMock()
    question = _question()
    service.get_active_session.return_value = None
    service.resume_or_start_session.return_value = (SimpleNamespace(id=10), question)

    _patch_service(monkeypatch, service, db)

    callback = _Callback(data="theme:A1:alltag")
    await training.handle_theme_selected(callback)

    callback.answer.assert_awaited_once()
    service.get_active_session.assert_awaited_once_with(db, 111)
    service.resume_or_start_session.assert_awaited_once_with(
        db,
        111,
        level="A1",
        theme="Alltag",
        force_new=False,
        total_questions=5,
    )

    callback.message.answer.assert_awaited_once()
    args = callback.message.answer.await_args.args
    kwargs = callback.message.answer.await_args.kwargs
    assert TRAINING_QUESTION_TEMPLATE.format(position=1, total=3, question_text="Was ist korrekt?") in args[0]
    button_texts = [button.text for row in kwargs["reply_markup"].inline_keyboard for button in row]
    assert button_texts == ["Option A", "Option B", "🏠 Hauptmenü"]


@pytest.mark.asyncio
async def test_handle_theme_selected_shows_resume_for_active_session(monkeypatch) -> None:
    db = FakeDb()
    service = AsyncMock()
    service.get_active_session.return_value = SimpleNamespace(id=99)

    _patch_service(monkeypatch, service, db)

    callback = _Callback(data="theme:A1:alltag")
    await training.handle_theme_selected(callback)

    callback.message.answer.assert_awaited_once()
    assert TRAINING_SESSION_RESUME_TEXT in _extract_text(callback.message.answer.await_args)
    payloads = _button_payloads(callback.message.answer.await_args.kwargs["reply_markup"])
    assert payloads == [f"train:resume:99", "train:new:99", "train:cancel:99", "bot:home"]
    assert service.resume_or_start_session.await_count == 0


@pytest.mark.asyncio
async def test_handle_theme_selected_without_level_prompts_level_picker(monkeypatch) -> None:
    db = FakeDb()
    service = AsyncMock()
    _patch_service(monkeypatch, service, db)

    callback = _Callback(data="theme::alltag")
    await training.handle_theme_selected(callback)

    callback.message.answer.assert_awaited_once()
    sent_text = _extract_text(callback.message.answer.await_args)
    assert TRAINING_NO_LEVEL_SELECTED_TEXT == sent_text
    payloads = _callback_payloads(callback.message.answer.await_args.kwargs["reply_markup"])
    assert payloads[:5] == ["level:A1", "level:A2", "level:B1", "level:B2", "level:C1"]
    assert service.resume_or_start_session.await_count == 0


@pytest.mark.asyncio
async def test_handle_submit_answer_returns_result_and_finish(monkeypatch) -> None:
    db = FakeDb()
    service = AsyncMock()
    service.submit_answer.return_value = AnswerResult(
        selected_answer="a",
        correct_answer="a",
        question_token="tok12345",
        is_correct=True,
        is_duplicate=False,
        is_completed=True,
        explanation="Korrekt erklärt.",
        correct_answers=3,
        total_questions=3,
        session_id=10,
    )

    _patch_service(monkeypatch, service, db)

    callback = _Callback(data="train:ans:10:tok12345:a")
    await training.handle_submit_answer(callback)

    callback.message.answer.assert_awaited_once()
    text = _extract_text(callback.message.answer.await_args)
    assert TRAINING_FINISH_TEXT.format(correct=3, total=3, percent=100) in text
    assert TRAINING_EXPLANATION_TEXT.format(explanation="Korrekt erklärt.") in text
    button_texts = [button.text for row in callback.message.answer.await_args.kwargs["reply_markup"].inline_keyboard for button in row]
    assert TRAINING_NEW_SESSION_BUTTON_TEXT in button_texts


@pytest.mark.asyncio
async def test_handle_submit_answer_shows_duplicate_warning_and_next_button(monkeypatch) -> None:
    db = FakeDb()
    service = AsyncMock()
    service.submit_answer.return_value = AnswerResult(
        selected_answer="a",
        correct_answer="a",
        question_token="tok12345",
        is_correct=True,
        is_duplicate=True,
        is_completed=False,
        explanation="Korrekt erklärt.",
        correct_answers=1,
        total_questions=3,
        session_id=10,
    )

    _patch_service(monkeypatch, service, db)

    callback = _Callback(data="train:ans:10:tok12345:a")
    await training.handle_submit_answer(callback)

    callback.message.answer.assert_awaited_once()
    text = _extract_text(callback.message.answer.await_args)
    assert TRAINING_ANSWER_DUPLICATE_TEXT in text
    button_texts = [
        button.text for row in callback.message.answer.await_args.kwargs["reply_markup"].inline_keyboard for button in row
    ]
    assert TRAINING_NEXT_BUTTON_TEXT in button_texts


@pytest.mark.asyncio
async def test_handle_submit_answer_shows_correct_answer_text_not_option_id(monkeypatch) -> None:
    db = FakeDb()
    service = AsyncMock()
    service.submit_answer.return_value = AnswerResult(
        selected_answer="b",
        correct_answer="a",
        question_token="tok12345",
        is_correct=False,
        is_duplicate=False,
        is_completed=False,
        explanation=None,
        correct_answers=0,
        total_questions=3,
        session_id=10,
        correct_answer_text="Option A",
    )

    _patch_service(monkeypatch, service, db)

    callback = _Callback(data="train:ans:10:tok12345:b")
    await training.handle_submit_answer(callback)

    text = _extract_text(callback.message.answer.await_args)
    assert "Option A" in text
    assert "`a`" not in text


@pytest.mark.asyncio
async def test_handle_next_question_shows_new_question(monkeypatch) -> None:
    db = FakeDb()
    service = AsyncMock()
    service.get_active_session.return_value = SimpleNamespace(
        id=10,
        api_metadata={"pending_question": {"question_token": "tok12345"}},
    )
    service.get_next_question.return_value = _question()

    _patch_service(monkeypatch, service, db)

    callback = _Callback(data="train:next:10:tok12345")
    await training.handle_next_question(callback)

    service.get_next_question.assert_awaited_once_with(
        db,
        111,
        session_id=10,
        answered_question_token="tok12345",
    )
    callback.message.answer.assert_awaited_once()
    args = callback.message.answer.await_args.args
    assert TRAINING_QUESTION_TEMPLATE.format(position=1, total=3, question_text="Was ist korrekt?") in args[0]


@pytest.mark.asyncio
async def test_handle_cancel_training_confirms_cancel(monkeypatch) -> None:
    db = FakeDb()
    service = AsyncMock()
    service.get_active_session.return_value = SimpleNamespace(id=10)
    service.cancel_active_session.return_value = True

    _patch_service(monkeypatch, service, db)

    callback = _Callback(data="train:cancel:10")
    await training.handle_cancel_training(callback)

    service.cancel_active_session.assert_awaited_once_with(db, 111)
    callback.message.answer.assert_awaited_once()
    sent_text = _extract_text(callback.message.answer.await_args)
    assert sent_text == training.TRAINING_SESSION_CANCELLED_TEXT
    keyboard_payloads = _callback_payloads(callback.message.answer.await_args.kwargs["reply_markup"])
    assert keyboard_payloads[:5] == ["level:A1", "level:A2", "level:B1", "level:B2", "level:C1"]


@pytest.mark.asyncio
async def test_handle_next_question_rejects_stale_token(monkeypatch) -> None:
    db = FakeDb()
    service = AsyncMock()
    service.get_active_session.return_value = SimpleNamespace(
        id=10,
        api_metadata={"pending_question": {"question_token": "new-token"}},
    )

    _patch_service(monkeypatch, service, db)

    callback = _Callback(data="train:next:10:old-token")
    await training.handle_next_question(callback)

    service.get_next_question.assert_not_awaited()
    callback.message.answer.assert_awaited_once_with(training.TRAINING_SESSION_ERROR_TEXT)


@pytest.mark.asyncio
async def test_handle_resume_training_shows_current_question(monkeypatch) -> None:
    db = FakeDb()
    service = AsyncMock()
    service.get_active_session.return_value = SimpleNamespace(id=10)
    service.get_or_create_current_question.return_value = _question()

    _patch_service(monkeypatch, service, db)

    callback = _Callback(data="train:resume:10")
    await training.handle_resume_training(callback)

    service.get_active_session.assert_awaited_once_with(db, 111)
    service.get_or_create_current_question.assert_awaited_once_with(db, 111, force_refresh=False)
    callback.message.answer.assert_awaited_once()
    args = callback.message.answer.await_args.args
    assert TRAINING_QUESTION_TEMPLATE.format(position=1, total=3, question_text="Was ist korrekt?") in args[0]


@pytest.mark.asyncio
async def test_build_resume_keyboard_is_reused_in_session_prompt() -> None:
    keyboard = build_resume_keyboard(session_id=99)
    payloads = _button_payloads(keyboard)
    assert payloads == ["train:resume:99", "train:new:99", "train:cancel:99", "bot:home"]
