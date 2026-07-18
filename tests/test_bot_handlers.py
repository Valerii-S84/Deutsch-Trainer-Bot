from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.bot.handlers import common as handler_common
from app.bot.handlers import fallback, menu
from app.bot.handlers import level as level_handlers
from app.bot.handlers import profile, start, subscription, theme
from app.bot.keyboards.levels import build_levels_keyboard
from app.bot.keyboards.main_menu import build_main_menu_keyboard
from app.catalog.service import LocalCatalogNotConfiguredError
from app.bot.texts import (
    LEVEL_CALLBACK_FALLBACK_TEXT,
    PROFILE_TEXT,
    SUBSCRIPTION_STATUS_FREE_TEXT,
    TRAINING_QUIZBANK_AUTH_ERROR_TEXT,
    TRAINING_QUIZBANK_RATE_LIMIT_TEXT,
    TRAINING_QUIZBANK_UNAVAILABLE_TEXT,
    TRAINING_QUIZBANK_VALIDATION_TEXT,
    UNKNOWN_CALLBACK_TEXT,
    UNKNOWN_MESSAGE_TEXT,
    WELCOME_TEXT,
    TRAINING_PROMPT,
    TRAINING_NO_LEVEL_SELECTED_TEXT,
)
from app.quiz_bank.schemas import QuizTheme, QuizThemesResponse
from app.quiz_bank.errors import (
    QuizBankAuthError,
    QuizBankRateLimitError,
    QuizBankUnavailableError,
    QuizBankValidationError,
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
        self.create_or_update_from_telegram = AsyncMock(return_value=SimpleNamespace(selected_level=None))
        self.get_by_telegram_id = AsyncMock(return_value=SimpleNamespace(selected_level=None, selected_theme=None))


class _CallbackQuery:
    def __init__(self, data: str | None = None, text: str | None = None) -> None:
        self.data = data
        self.message = _Message(text=text, first_name="Test")
        self.from_user = SimpleNamespace(id=111)
        self.answer = AsyncMock()


class _TrainingService:
    def __init__(self) -> None:
        self.cancel_active_session = AsyncMock(return_value=True)


class _CatalogService:
    def __init__(self, themes: list[QuizTheme] | None = None) -> None:
        self.get_themes = AsyncMock(
            return_value=QuizThemesResponse(
                level="A1",
                themes=themes or [QuizTheme(theme="Alltag", theme_key="T01", is_active=True, available_items_count=3)],
            ),
        )


def test_common_extract_user_id_reads_nested_from_user() -> None:
    event = SimpleNamespace(from_user=SimpleNamespace(id=111))

    assert handler_common.extract_user_id(event) == 111


def test_common_extract_user_id_handles_missing_user() -> None:
    assert handler_common.extract_user_id(SimpleNamespace(from_user=None)) is None


def test_common_quizbank_error_mapping_preserves_german_copy() -> None:
    assert handler_common.map_quizbank_error(QuizBankAuthError("auth")) == TRAINING_QUIZBANK_AUTH_ERROR_TEXT
    assert handler_common.map_quizbank_error(QuizBankRateLimitError("rate")) == TRAINING_QUIZBANK_RATE_LIMIT_TEXT
    assert handler_common.map_quizbank_error(QuizBankUnavailableError("down")) == TRAINING_QUIZBANK_UNAVAILABLE_TEXT
    assert handler_common.map_quizbank_error(QuizBankValidationError("bad")) == TRAINING_QUIZBANK_VALIDATION_TEXT


def test_common_quizbank_error_mapping_uses_configured_default() -> None:
    assert handler_common.map_quizbank_error(RuntimeError("unknown"), default_text="fallback") == "fallback"


@pytest.mark.asyncio
async def test_start_handler_routes_new_user_to_level_selection(monkeypatch) -> None:
    db = _Db()
    user_repo = _UserRepo()
    monkeypatch.setattr(start, "_session_factory", lambda: _SessionContext(db))
    monkeypatch.setattr(start, "_user_repo", user_repo)

    message = _Message(text="/start", first_name="Anna_Test", user_id=111)
    await start.handle_start(message)

    user_repo.create_or_update_from_telegram.assert_awaited_once_with(db, message.from_user)
    db.commit.assert_awaited_once()
    message.answer.assert_awaited_once()
    args = message.answer.await_args.args
    kwargs = message.answer.await_args.kwargs
    assert args[0] == TRAINING_PROMPT
    assert kwargs["reply_markup"].inline_keyboard == build_levels_keyboard().inline_keyboard


@pytest.mark.asyncio
async def test_start_handler_shows_main_menu_for_returning_user(monkeypatch) -> None:
    db = _Db()
    user_repo = _UserRepo()
    user_repo.create_or_update_from_telegram.return_value = SimpleNamespace(selected_level="A1")
    monkeypatch.setattr(start, "_session_factory", lambda: _SessionContext(db))
    monkeypatch.setattr(start, "_user_repo", user_repo)

    message = _Message(text="/start", first_name="Anna_Test", user_id=111)
    await start.handle_start(message)

    kwargs = message.answer.await_args.kwargs
    assert WELCOME_TEXT in kwargs["text"]
    assert "Hallo *Anna\\_Test*" in kwargs["text"]
    assert kwargs["parse_mode"] == "Markdown"
    assert kwargs["reply_markup"].inline_keyboard == build_main_menu_keyboard().inline_keyboard


@pytest.mark.asyncio
async def test_open_menu_from_callback_shows_menu(monkeypatch) -> None:
    db = _Db()
    training_service = _TrainingService()
    user_repo = _UserRepo()
    monkeypatch.setattr(menu, "_session_factory", lambda: _SessionContext(db))
    monkeypatch.setattr(menu, "_training_service", training_service)
    monkeypatch.setattr(menu, "_user_repo", user_repo)

    callback = _CallbackQuery(data="bot:home", text="menu")
    await menu.open_menu_from_callback(callback)

    training_service.cancel_active_session.assert_awaited_once_with(db, 111)
    db.commit.assert_awaited_once()
    callback.message.answer.assert_awaited_once()
    callback.answer.assert_awaited_once()


@pytest.mark.asyncio
async def test_continue_menu_uses_active_session_without_cancelling(monkeypatch) -> None:
    db = _Db()
    training_service = _TrainingService()
    continue_active = AsyncMock(return_value=True)
    start_saved = AsyncMock()
    monkeypatch.setattr(menu, "_session_factory", lambda: _SessionContext(db))
    monkeypatch.setattr(menu, "_training_service", training_service)
    monkeypatch.setattr(menu, "continue_active_training_from_message", continue_active)
    monkeypatch.setattr(menu, "start_saved_theme_training_from_message", start_saved)

    callback = _CallbackQuery(data="menu:continue")
    await menu.continue_training(callback)

    callback.answer.assert_awaited_once()
    continue_active.assert_awaited_once_with(callback.message, 111)
    start_saved.assert_not_awaited()
    training_service.cancel_active_session.assert_not_awaited()


@pytest.mark.asyncio
async def test_continue_menu_starts_saved_theme(monkeypatch) -> None:
    user_repo = _UserRepo()
    user_repo.get_by_telegram_id.return_value = SimpleNamespace(selected_level="A1", selected_theme="T01")
    continue_active = AsyncMock(return_value=False)
    start_saved = AsyncMock()
    monkeypatch.setattr(menu, "_session_factory", lambda: _SessionContext(_Db()))
    monkeypatch.setattr(menu, "_user_repo", user_repo)
    monkeypatch.setattr(menu, "continue_active_training_from_message", continue_active)
    monkeypatch.setattr(menu, "start_saved_theme_training_from_message", start_saved)

    callback = _CallbackQuery(data="menu:continue")
    await menu.continue_training(callback)

    start_saved.assert_awaited_once_with(callback.message, 111, level="A1", theme="T01")


@pytest.mark.asyncio
async def test_continue_menu_with_only_level_opens_theme_groups(monkeypatch) -> None:
    user_repo = _UserRepo()
    catalog_service = _CatalogService()
    user_repo.get_by_telegram_id.return_value = SimpleNamespace(selected_level="A1", selected_theme=None)
    monkeypatch.setattr(menu, "_session_factory", lambda: _SessionContext(_Db()))
    monkeypatch.setattr(menu, "_user_repo", user_repo)
    monkeypatch.setattr(menu, "_catalog_service", lambda: catalog_service)
    monkeypatch.setattr(menu, "continue_active_training_from_message", AsyncMock(return_value=False))

    callback = _CallbackQuery(data="menu:continue")
    await menu.continue_training(callback)

    catalog_service.get_themes.assert_awaited_once()
    callback.message.answer.assert_awaited_once()
    payloads = [button.callback_data for row in callback.message.answer.await_args.kwargs["reply_markup"].inline_keyboard for button in row]
    assert "group:A1:G01" in payloads


@pytest.mark.asyncio
async def test_continue_menu_without_level_opens_level_selection(monkeypatch) -> None:
    user_repo = _UserRepo()
    user_repo.get_by_telegram_id.return_value = SimpleNamespace(selected_level=None, selected_theme=None)
    monkeypatch.setattr(menu, "_session_factory", lambda: _SessionContext(_Db()))
    monkeypatch.setattr(menu, "_user_repo", user_repo)
    monkeypatch.setattr(menu, "continue_active_training_from_message", AsyncMock(return_value=False))

    callback = _CallbackQuery(data="menu:continue")
    await menu.continue_training(callback)

    callback.message.answer.assert_awaited_once()
    assert callback.message.answer.await_args.args[0] == TRAINING_PROMPT


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
    assert "Dein Abo" in args[0]
    assert SUBSCRIPTION_STATUS_FREE_TEXT in args[0]
    assert "Subscription" not in args[0]
    assert "Payment" not in args[0]
    assert "Free" not in args[0]
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


@pytest.mark.asyncio
async def test_theme_groups_reject_unknown_level_before_catalog_lookup(monkeypatch) -> None:
    catalog_service = _CatalogService()
    monkeypatch.setattr(theme, "_catalog_service", lambda: catalog_service)

    callback = _CallbackQuery(data="groups:ZZ")

    await theme.open_theme_groups_for_level(callback)

    catalog_service.get_themes.assert_not_awaited()
    callback.message.answer.assert_awaited_once()
    assert callback.message.answer.await_args.args[0] == TRAINING_NO_LEVEL_SELECTED_TEXT
    assert callback.message.answer.await_args.kwargs["reply_markup"].inline_keyboard == build_levels_keyboard().inline_keyboard


@pytest.mark.asyncio
async def test_theme_group_rejects_tampered_payload_with_german_fallback() -> None:
    callback = _CallbackQuery(data="group:A1:UNKNOWN")

    await theme.open_theme_group(callback)

    callback.message.answer.assert_awaited_once()
    assert callback.message.answer.await_args.args[0] == theme.THEME_CALLBACK_FALLBACK_TEXT


@pytest.mark.asyncio
async def test_theme_group_shows_only_available_themes_for_selected_group(monkeypatch) -> None:
    catalog_service = _CatalogService(
        themes=[
            QuizTheme(theme="Alltag", theme_key="T01", is_active=True, available_items_count=3),
            QuizTheme(theme="Familie", theme_key="T02", is_active=True, available_items_count=2),
            QuizTheme(theme="Arbeit", theme_key="T06", is_active=True, available_items_count=5),
        ],
    )
    monkeypatch.setattr(theme, "_catalog_service", lambda: catalog_service)
    monkeypatch.setattr(theme, "_session_factory", lambda: _SessionContext(_Db()))

    callback = _CallbackQuery(data="group:A1:G01")

    await theme.open_theme_group(callback)

    callback.message.answer.assert_awaited_once()
    text = callback.message.answer.await_args.args[0]
    payloads = [
        button.callback_data
        for row in callback.message.answer.await_args.kwargs["reply_markup"].inline_keyboard
        for button in row
    ]
    assert "Ich & Alltag" in text
    assert "theme:A1:T01" in payloads
    assert "theme:A1:T02" in payloads
    assert "theme:A1:T06" not in payloads
    assert "groups:A1" in payloads


@pytest.mark.asyncio
async def test_theme_group_catalog_unavailable_uses_level_picker_recovery(monkeypatch) -> None:
    catalog_service = _CatalogService()
    catalog_service.get_themes.side_effect = LocalCatalogNotConfiguredError("missing catalog")
    monkeypatch.setattr(theme, "_catalog_service", lambda: catalog_service)
    monkeypatch.setattr(theme, "_session_factory", lambda: _SessionContext(_Db()))

    callback = _CallbackQuery(data="group:A1:G01")

    await theme.open_theme_group(callback)

    callback.message.answer.assert_awaited_once()
    assert callback.message.answer.await_args.args[0] == TRAINING_QUIZBANK_UNAVAILABLE_TEXT
    assert callback.message.answer.await_args.kwargs["reply_markup"].inline_keyboard == build_levels_keyboard().inline_keyboard
