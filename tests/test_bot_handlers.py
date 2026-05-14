from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.bot.handlers import fallback, menu
from app.bot.handlers import level as level_handlers
from app.bot.handlers import profile, start, subscription, theme
from app.bot.keyboards.main_menu import build_main_menu_keyboard
from app.bot.texts import (
    LEVEL_CALLBACK_FALLBACK_TEXT,
    PROFILE_TEXT,
    SUBSCRIPTION_TEXT,
    UNKNOWN_CALLBACK_TEXT,
    UNKNOWN_MESSAGE_TEXT,
    WELCOME_TEXT,
)


class _Message:
    def __init__(
        self,
        text: str | None = None,
        first_name: str | None = None,
        user_id: int | None = None,
    ) -> None:
        self.text = text
        self.from_user = SimpleNamespace(
            id=user_id,
            first_name=first_name,
            username="anna",
            language_code="de",
        )
        self.answer = AsyncMock()


class _Db:
    def __init__(self) -> None:
        self.commit = AsyncMock()
        self.rollback = AsyncMock()


class _SessionContext:
    def __init__(self, db: _Db) -> None:
        self.db = db

    async def __aenter__(self) -> _Db:
        return self.db

    async def __aexit__(self, exc_type, exc, tb) -> None:  # type: ignore[override]
        return None


class _UserRepo:
    def __init__(self) -> None:
        self.create_or_update_from_telegram = AsyncMock()


class _CallbackQuery:
    def __init__(self, data: str | None = None, text: str | None = None) -> None:
        self.data = data
        self.message = _Message(text=text, first_name="Test")
        self.from_user = SimpleNamespace(id=111)
        self.answer = AsyncMock()


class _TrainingService:
    def __init__(self) -> None:
        self.cancel_active_session = AsyncMock(return_value=True)


@pytest.mark.asyncio
async def test_start_handler_shows_main_menu_and_remembers_user(monkeypatch) -> None:
    db = _Db()
    user_repo = _UserRepo()
    monkeypatch.setattr(start, "_session_factory", lambda: _SessionContext(db))
    monkeypatch.setattr(start, "_user_repo", user_repo)

    message = _Message(text="/start", first_name="Anna_Test", user_id=111)
    await start.handle_start(message)

    user_repo.create_or_update_from_telegram.assert_awaited_once_with(db, message.from_user)
    db.commit.assert_awaited_once()
    message.answer.assert_awaited_once()
    kwargs = message.answer.await_args.kwargs
    assert WELCOME_TEXT in kwargs["text"]
    assert "Hallo *Anna\\_Test*" in kwargs["text"]
    assert kwargs["parse_mode"] == "Markdown"
    assert kwargs["reply_markup"].inline_keyboard == build_main_menu_keyboard().inline_keyboard


@pytest.mark.asyncio
async def test_open_menu_from_callback_shows_menu(monkeypatch) -> None:
    db = _Db()
    training_service = _TrainingService()
    monkeypatch.setattr(menu, "_session_factory", lambda: _SessionContext(db))
    monkeypatch.setattr(menu, "_training_service", training_service)

    callback = _CallbackQuery(data="bot:home", text="menu")
    await menu.open_menu_from_callback(callback)

    training_service.cancel_active_session.assert_awaited_once_with(db, 111)
    db.commit.assert_awaited_once()
    callback.message.answer.assert_awaited_once()
    callback.answer.assert_awaited_once()


@pytest.mark.asyncio
async def test_level_flow_with_unknown_level_is_safe() -> None:
    callback = _CallbackQuery(data="level:ZZ")
    await level_handlers.level_selected(callback)
    callback.message.answer.assert_awaited_once()
    callback.message.answer.assert_awaited_with(LEVEL_CALLBACK_FALLBACK_TEXT)
@pytest.mark.asyncio
async def test_profile_entry_point_is_static_message() -> None:
    message = _Message(text="/profile")
    await profile.handle_profile_message(message)
    args = message.answer.await_args.args
    kwargs = message.answer.await_args.kwargs
    assert PROFILE_TEXT in args[0]
    assert kwargs["reply_markup"] is not None


@pytest.mark.asyncio
async def test_subscription_entry_point_is_static_message() -> None:
    message = _Message(text="/subscription")
    await subscription.handle_subscription_message(message)
    args = message.answer.await_args.args
    assert SUBSCRIPTION_TEXT in args[0]
    assert "Subscription" not in args[0]
    assert "Payment" not in args[0]
    assert "Milestone" not in args[0]


@pytest.mark.asyncio
async def test_fallback_message_handler_responds() -> None:
    message = _Message(text="random text")
    await fallback.fallback_text(message)
    message.answer.assert_awaited_once_with(UNKNOWN_MESSAGE_TEXT)


@pytest.mark.asyncio
async def test_fallback_callback_handler_responds() -> None:
    callback = _CallbackQuery(data="invalid:payload")
    await fallback.fallback_callback(callback)
    callback.answer.assert_awaited_once_with(UNKNOWN_CALLBACK_TEXT, show_alert=True)
