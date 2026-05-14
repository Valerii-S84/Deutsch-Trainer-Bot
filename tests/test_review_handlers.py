from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.bot.handlers import review
from app.bot.texts import REVIEW_EMPTY_STATE_TEXT, TRAINING_QUESTION_TEMPLATE
from app.services.training_session import NoReviewItemsError


class FakeDb:
    def __init__(self) -> None:
        self.committed = 0
        self.rolled_back = 0

    async def commit(self) -> None:
        self.committed += 1

    async def rollback(self) -> None:
        self.rolled_back += 1


class FakeMessage:
    def __init__(self) -> None:
        self.answer = AsyncMock()


class FakeCallback:
    def __init__(self, data: str | None = None) -> None:
        self.data = data
        self.from_user = SimpleNamespace(id=111)
        self.message = FakeMessage()
        self.answer = AsyncMock()


class FakeQuestion:
    def __init__(self, session_id: int = 11) -> None:
        self.session_id = session_id
        self.question_token = "tok-11"
        self.question_id = "q11"
        self.question_text = "Was ist korrekt?"
        self.answer_options = (("a1", "Option A"), ("a2", "Option B"))
        self.position = 1
        self.total_questions = 3


class FakeReviewService:
    def __init__(self, should_raise: Exception | None = None) -> None:
        self.should_raise = should_raise
        self.resume_called = False

    async def resume_or_start_review_session(self, db, user_id, *, force_new: bool, total_questions: int):
        self.resume_called = True
        if self.should_raise:
            raise self.should_raise
        return SimpleNamespace(id=11), FakeQuestion()


@pytest.mark.asyncio
async def test_review_entry_shows_empty_state_when_no_active_mistakes(monkeypatch) -> None:
    db = FakeDb()
    fake_service = FakeReviewService(should_raise=NoReviewItemsError("no mistakes"))
    monkeypatch.setattr(review, "review_service", fake_service)
    monkeypatch.setattr(review, "_session_factory", lambda: db)

    callback = FakeCallback(data="menu:review")
    await review.handle_review_entry(callback)

    callback.answer.assert_awaited_once()
    callback.message.answer.assert_awaited_once()
    call_kwargs = callback.message.answer.await_args.kwargs
    text = callback.message.answer.await_args.args[0]
    assert REVIEW_EMPTY_STATE_TEXT == text
    assert call_kwargs["reply_markup"] is not None
    assert fake_service.resume_called


@pytest.mark.asyncio
async def test_review_entry_starts_session_and_shows_question(monkeypatch) -> None:
    db = FakeDb()
    fake_service = FakeReviewService()
    monkeypatch.setattr(review, "review_service", fake_service)
    monkeypatch.setattr(review, "_session_factory", lambda: db)

    callback = FakeCallback(data="menu:review")
    await review.handle_review_entry(callback)

    callback.message.answer.assert_awaited_once()
    message = callback.message.answer.await_args.args[0]
    assert TRAINING_QUESTION_TEMPLATE.format(position=1, total=3, question_text="Was ist korrekt?") in message
