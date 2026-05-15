from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.bot.handlers import review
from app.bot.texts import (
    PAYWALL_DAILY_LIMIT_TEXT,
    PAYWALL_MISTAKE_REPEAT_TEXT,
    REVIEW_EMPTY_STATE_TEXT,
    REVIEW_SCREEN_TEXT,
    TRAINING_QUESTION_TEMPLATE,
)
from app.services.entitlements import DailyLimitExceededError, EntitlementDeniedError


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


class FakeMistakeService:
    def __init__(self, items: list[object] | None = None) -> None:
        self.items = items or []
        self.called = False

    async def get_review_items(self, db, user_id: int):
        self.called = True
        return self.items


class FakeEntitlementService:
    def __init__(self, should_raise: Exception | None = None) -> None:
        self.should_raise = should_raise
        self.called = False

    async def ensure_entitlement(self, db, user_id: int, *, feature: str):
        self.called = True
        if self.should_raise is not None:
            raise self.should_raise
        return SimpleNamespace(allowed=True)


def _daily_limit_error() -> DailyLimitExceededError:
    state = SimpleNamespace(
        plan="free",
        question_limit=1,
        questions_used=1,
        remaining=0,
        reset_at=None,
        daily_limit=SimpleNamespace(id=77, user_id=111),
    )
    return DailyLimitExceededError(state)


@pytest.mark.asyncio
async def test_review_entry_shows_empty_state_when_no_active_mistakes(monkeypatch) -> None:
    db = FakeDb()
    fake_mistakes = FakeMistakeService(items=[])
    fake_entitlements = FakeEntitlementService()
    monkeypatch.setattr(review, "mistake_service", fake_mistakes)
    monkeypatch.setattr(review, "entitlement_service", fake_entitlements)
    monkeypatch.setattr(review, "_session_factory", lambda: db)

    callback = FakeCallback(data="menu:review")
    await review.handle_review_entry(callback)

    callback.answer.assert_awaited_once()
    callback.message.answer.assert_awaited_once()
    call_kwargs = callback.message.answer.await_args.kwargs
    text = callback.message.answer.await_args.args[0]
    assert REVIEW_EMPTY_STATE_TEXT == text
    assert call_kwargs["reply_markup"] is not None
    assert fake_mistakes.called
    assert not fake_entitlements.called


@pytest.mark.asyncio
async def test_review_entry_shows_active_mistake_screen(monkeypatch) -> None:
    db = FakeDb()
    fake_mistakes = FakeMistakeService(items=[SimpleNamespace(id=1)])
    monkeypatch.setattr(review, "mistake_service", fake_mistakes)
    monkeypatch.setattr(review, "entitlement_service", FakeEntitlementService())
    monkeypatch.setattr(review, "_session_factory", lambda: db)

    callback = FakeCallback(data="menu:review")
    await review.handle_review_entry(callback)

    callback.message.answer.assert_awaited_once()
    text = callback.message.answer.await_args.args[0]
    payloads = [
        button.callback_data
        for row in callback.message.answer.await_args.kwargs["reply_markup"].inline_keyboard
        for button in row
    ]
    assert REVIEW_SCREEN_TEXT == text
    assert payloads == ["review:start", "menu:profile", "bot:home"]


@pytest.mark.asyncio
async def test_review_start_starts_session_and_shows_question(monkeypatch) -> None:
    db = FakeDb()
    fake_service = FakeReviewService()
    monkeypatch.setattr(review, "review_service", fake_service)
    monkeypatch.setattr(review, "_session_factory", lambda: db)

    callback = FakeCallback(data="review:start")
    await review.handle_review_start(callback)

    callback.message.answer.assert_awaited_once()
    message = callback.message.answer.await_args.args[0]
    assert TRAINING_QUESTION_TEMPLATE.format(position=1, total=3, question_text="Was ist korrekt?") in message


@pytest.mark.asyncio
async def test_review_entry_shows_paywall_without_mistake_repeat_entitlement(monkeypatch) -> None:
    db = FakeDb()
    decision = SimpleNamespace(reason_code="entitlement_required")
    monkeypatch.setattr(review, "mistake_service", FakeMistakeService(items=[SimpleNamespace(id=1)]))
    monkeypatch.setattr(review, "entitlement_service", FakeEntitlementService(EntitlementDeniedError(decision)))
    monkeypatch.setattr(review, "_session_factory", lambda: db)

    callback = FakeCallback(data="menu:review")
    await review.handle_review_entry(callback)

    text = callback.message.answer.await_args.args[0]
    payloads = [
        button.callback_data
        for row in callback.message.answer.await_args.kwargs["reply_markup"].inline_keyboard
        for button in row
    ]
    assert PAYWALL_MISTAKE_REPEAT_TEXT == text
    assert "menu:subscription" in payloads
    assert db.rolled_back == 1


@pytest.mark.asyncio
async def test_review_entry_shows_daily_limit_paywall(monkeypatch) -> None:
    db = FakeDb()
    fake_service = FakeReviewService(should_raise=_daily_limit_error())
    monkeypatch.setattr(review, "review_service", fake_service)
    monkeypatch.setattr(review, "_session_factory", lambda: db)

    callback = FakeCallback(data="review:start")
    await review.handle_review_start(callback)

    text = callback.message.answer.await_args.args[0]
    payloads = [
        button.callback_data
        for row in callback.message.answer.await_args.kwargs["reply_markup"].inline_keyboard
        for button in row
    ]
    assert PAYWALL_DAILY_LIMIT_TEXT == text
    assert "menu:subscription" in payloads
    assert db.rolled_back == 1
