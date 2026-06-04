from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.bot.handlers import subscription
from app.bot.texts import (
    SUBSCRIPTION_STATUS_FREE_TEXT,
    SUBSCRIPTION_STATUS_INACTIVE_TEXT,
)


class FakeDb:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:  # type: ignore[override]
        return None


class FakeMessage:
    def __init__(self, from_user_id: int | None = 111) -> None:
        self.from_user = SimpleNamespace(id=from_user_id) if from_user_id is not None else None
        self.answer = AsyncMock()


class FakeCallback:
    def __init__(self, from_user_id: int = 111) -> None:
        self.from_user = SimpleNamespace(id=from_user_id)
        self.message = FakeMessage(from_user_id)
        self.answer = AsyncMock()


class FakeEntitlementService:
    def __init__(self, status_state) -> None:
        self.status_state = status_state

    async def get_subscription_status_state(self, db, telegram_user_id: int):
        return self.status_state


def _state(
    *,
    access_plan: str,
    status_plan: str,
    status: str,
    expires_at: datetime | None = None,
):
    return SimpleNamespace(
        access_plan=access_plan,
        status_plan=status_plan,
        status=status,
        expires_at=expires_at,
    )


def _sent_text(call) -> str:
    return call.args[0] if call.args else ""


@pytest.mark.asyncio
async def test_subscription_message_shows_free_state_without_user(monkeypatch) -> None:
    monkeypatch.setattr(subscription, "_session_factory", lambda: FakeDb())

    message = FakeMessage(from_user_id=None)
    await subscription.handle_subscription_message(message)

    text = _sent_text(message.answer.await_args)
    assert "Dein Abo" in text
    assert f"Aktueller Zugang: {SUBSCRIPTION_STATUS_FREE_TEXT}" in text
    assert SUBSCRIPTION_STATUS_INACTIVE_TEXT in text


@pytest.mark.asyncio
async def test_subscription_callback_shows_active_paid_status(monkeypatch) -> None:
    status_state = _state(
        access_plan="plus",
        status_plan="plus",
        status="active",
        expires_at=datetime(2026, 5, 20, 10, 0, tzinfo=UTC),
    )
    monkeypatch.setattr(subscription, "_session_factory", lambda: FakeDb())
    monkeypatch.setattr(subscription, "_entitlement_service", FakeEntitlementService(status_state))

    callback = FakeCallback()
    await subscription.handle_subscription_callback(callback)

    text = _sent_text(callback.message.answer.await_args)
    assert "Aktueller Zugang: Plus" in text
    assert "Plus aktiv bis 20.05.2026" in text


@pytest.mark.asyncio
async def test_subscription_callback_keeps_pending_paid_status_on_free_access(monkeypatch) -> None:
    status_state = _state(access_plan="free", status_plan="pro", status="pending")
    monkeypatch.setattr(subscription, "_session_factory", lambda: FakeDb())
    monkeypatch.setattr(subscription, "_entitlement_service", FakeEntitlementService(status_state))

    callback = FakeCallback()
    await subscription.handle_subscription_callback(callback)

    text = _sent_text(callback.message.answer.await_args)
    assert "Aktueller Zugang: Free" in text
    assert "Pro wartet auf Zahlungsbestätigung" in text


@pytest.mark.asyncio
async def test_subscription_callback_shows_expired_paid_status_as_free_access(monkeypatch) -> None:
    status_state = _state(
        access_plan="free",
        status_plan="plus",
        status="expired",
        expires_at=datetime(2026, 5, 14, 10, 0, tzinfo=UTC),
    )
    monkeypatch.setattr(subscription, "_session_factory", lambda: FakeDb())
    monkeypatch.setattr(subscription, "_entitlement_service", FakeEntitlementService(status_state))

    callback = FakeCallback()
    await subscription.handle_subscription_callback(callback)

    text = _sent_text(callback.message.answer.await_args)
    assert "Aktueller Zugang: Free" in text
    assert "Plus ist am 14.05.2026 abgelaufen" in text
