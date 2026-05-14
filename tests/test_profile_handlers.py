from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.bot.handlers import profile
from app.bot.texts import PROFILE_EMPTY_STATE_TEXT, PROFILE_PROGRESS_TEMPLATE, PROFILE_TEXT


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


def _extract_text(call) -> str:
    return call.args[0] if call.args else ""


@pytest.mark.asyncio
async def test_profile_message_shows_empty_state(monkeypatch) -> None:
    db = FakeDb()
    message = FakeMessage()
    fake_service = FakeProgressService(rows=[])

    monkeypatch.setattr(profile, "_session_factory", lambda: db)
    monkeypatch.setattr(profile, "_progress_service", fake_service)

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

    await profile.handle_profile_callback(callback)

    called_args = callback.message.answer.await_args
    assert called_args is not None
    text = _extract_text(called_args)
    assert PROFILE_TEXT in text
    assert PROFILE_PROGRESS_TEMPLATE.format(
        level="A1",
        theme="Alltag",
        correct=2,
        answered=3,
        accuracy=Decimal("66.67"),
    ) in text
