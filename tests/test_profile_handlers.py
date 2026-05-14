from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.bot.handlers import profile
from app.bot.texts import (
    CALLBACK_SUBSCRIPTION,
    PAYWALL_PROGRESS_TEXT,
    PROFILE_EMPTY_STATE_TEXT,
    PROFILE_PROGRESS_TEMPLATE,
    PROFILE_RECOMMENDATION_HEADER,
    PROFILE_TEXT,
    PROFILE_WEAK_THEMES_HEADER,
)


class FakeDb:
    def __init__(self) -> None:
        self.committed = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:  # type: ignore[override]
        return None


class FakeMessage:
    def __init__(self, from_user_id: int = 111) -> None:
        self.from_user = SimpleNamespace(id=from_user_id)
        self.answer = AsyncMock()


class FakeCallback:
    def __init__(self, from_user_id: int = 111, data: str | None = None) -> None:
        self.from_user = SimpleNamespace(id=from_user_id)
        self.data = data
        self.message = FakeMessage(from_user_id)
        self.answer = AsyncMock()


class FakeProgress:
    def __init__(
        self,
        level: str,
        theme: str | None,
        total_answered: int,
        total_correct: int,
        accuracy: Decimal,
    ) -> None:
        self.level = level
        self.theme = theme
        self.total_answered = total_answered
        self.total_correct = total_correct
        self.accuracy = accuracy


class FakeProgressService:
    def __init__(self, rows: list[FakeProgress]) -> None:
        self.rows = rows

    async def get_user_summary(self, db, telegram_user_id: int) -> list[FakeProgress]:
        return self.rows

    def build_recommendation_text(self, progress_records: list[FakeProgress]) -> str:
        return "Mach mit einer kurzen Übung weiter, um deinen Fortschritt zu festigen."


class FakeEntitlementService:
    def __init__(self, *, allowed: bool = True) -> None:
        self.allowed = allowed

    async def check_entitlement(self, db, telegram_user_id: int, *, feature: str):
        return SimpleNamespace(allowed=self.allowed)


def _extract_text(call) -> str:
    return call.args[0] if call.args else ""


@pytest.mark.asyncio
async def test_profile_message_shows_empty_state(monkeypatch) -> None:
    db = FakeDb()
    message = FakeMessage()
    fake_service = FakeProgressService(rows=[])

    monkeypatch.setattr(profile, "_session_factory", lambda: db)
    monkeypatch.setattr(profile, "_progress_service", fake_service)
    monkeypatch.setattr(profile, "_entitlement_service", FakeEntitlementService())

    await profile.handle_profile_message(message)

    called_args = message.answer.await_args
    assert called_args is not None
    assert PROFILE_TEXT in _extract_text(called_args)
    assert PROFILE_EMPTY_STATE_TEXT in _extract_text(called_args)


@pytest.mark.asyncio
async def test_profile_callback_shows_progress_lines(monkeypatch) -> None:
    db = FakeDb()
    callback = FakeCallback(data="menu:profile")
    fake_service = FakeProgressService(
        rows=[
            FakeProgress(level="A1", theme="Alltag", total_answered=3, total_correct=2, accuracy=Decimal("66.67")),
            FakeProgress(level="B1", theme="Beruf", total_answered=2, total_correct=1, accuracy=Decimal("50.00")),
        ],
    )

    monkeypatch.setattr(profile, "_session_factory", lambda: db)
    monkeypatch.setattr(profile, "_progress_service", fake_service)
    monkeypatch.setattr(profile, "_entitlement_service", FakeEntitlementService())

    await profile.handle_profile_callback(callback)

    called_args = callback.message.answer.await_args
    assert called_args is not None
    text = _extract_text(called_args)
    assert PROFILE_TEXT in text
    assert PROFILE_WEAK_THEMES_HEADER in text
    assert PROFILE_RECOMMENDATION_HEADER in text
    assert PROFILE_PROGRESS_TEMPLATE.format(
        status_icon="📘",
        level="A1",
        theme="Alltag",
        correct=2,
        answered=3,
        accuracy=Decimal("66.67"),
        coverage="offen",
        stability="0",
        weakness="0",
    ) in text


@pytest.mark.asyncio
async def test_profile_callback_shows_paywall_for_full_progress_without_entitlement(monkeypatch) -> None:
    db = FakeDb()
    callback = FakeCallback(data="menu:profile")
    fake_service = FakeProgressService(
        rows=[
            FakeProgress(level="A1", theme="Alltag", total_answered=12, total_correct=9, accuracy=Decimal("75.00")),
            FakeProgress(level="B1", theme="Beruf", total_answered=8, total_correct=3, accuracy=Decimal("37.50")),
        ],
    )

    monkeypatch.setattr(profile, "_session_factory", lambda: db)
    monkeypatch.setattr(profile, "_progress_service", fake_service)
    monkeypatch.setattr(profile, "_entitlement_service", FakeEntitlementService(allowed=False))

    await profile.handle_profile_callback(callback)

    called_args = callback.message.answer.await_args
    assert called_args is not None
    text = _extract_text(called_args)
    payloads = [
        button.callback_data
        for row in called_args.kwargs["reply_markup"].inline_keyboard
        for button in row
    ]
    assert PROFILE_TEXT in text
    assert PAYWALL_PROGRESS_TEXT in text
    assert PROFILE_WEAK_THEMES_HEADER not in text
    assert CALLBACK_SUBSCRIPTION in payloads
