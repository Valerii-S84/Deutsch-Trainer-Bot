from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.bot.handlers import admin
from app.bot.texts import ADMIN_METRICS_UNAUTHORIZED_TEXT
from app.config import Settings
from app.services.analytics import (
    AdminMetricsSnapshot,
    ConversionMetrics,
    DailyAdminMetrics,
    RateMetric,
    RetentionMetrics,
)


class FakeDb:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:  # type: ignore[override]
        return None


class FakeMessage:
    def __init__(self, from_user_id: int | None) -> None:
        self.from_user = SimpleNamespace(id=from_user_id) if from_user_id is not None else None
        self.answer = AsyncMock()


class FakeMetricsService:
    def __init__(self) -> None:
        self.called = False

    async def get_admin_metrics(self, db):
        self.called = True
        return _snapshot()


@pytest.mark.asyncio
async def test_admin_metrics_rejects_non_admin(monkeypatch) -> None:
    service = FakeMetricsService()
    monkeypatch.setattr(admin, "_metrics_service", service)
    monkeypatch.setattr(admin, "_settings", lambda: Settings(ADMIN_TELEGRAM_USER_IDS="111"))

    message = FakeMessage(from_user_id=222)
    await admin.handle_admin_metrics(message)

    message.answer.assert_awaited_once_with(ADMIN_METRICS_UNAUTHORIZED_TEXT)
    assert service.called is False


@pytest.mark.asyncio
async def test_admin_metrics_returns_report_for_configured_owner(monkeypatch) -> None:
    service = FakeMetricsService()
    monkeypatch.setattr(admin, "_metrics_service", service)
    monkeypatch.setattr(admin, "_session_factory", lambda: FakeDb())
    monkeypatch.setattr(admin, "_settings", lambda: Settings(ADMIN_TELEGRAM_USER_IDS="111"))

    message = FakeMessage(from_user_id=111)
    await admin.handle_admin_metrics(message)

    text = message.answer.await_args.args[0]
    assert service.called is True
    assert "Admin-Metriken" in text
    assert "Nutzer gesamt: 1" in text


def _snapshot() -> AdminMetricsSnapshot:
    zero = RateMetric(numerator=0, denominator=0, rate=None)
    return AdminMetricsSnapshot(
        generated_at=datetime(2026, 5, 15, 10, 0, tzinfo=UTC),
        daily=DailyAdminMetrics(
            total_users=1,
            new_users_today=1,
            active_users_today=1,
            training_sessions_today=1,
            answers_today=1,
            session_completion_rate_today=RateMetric(1, 1, 1.0),
            progress_opened_today=0,
            mistakes_repeated_today=0,
            active_subscriptions=0,
            payment_errors_today=0,
            api_errors_today=0,
        ),
        conversion=ConversionMetrics(
            paywall_ctr_today=zero,
            payment_success_rate_today=zero,
            free_to_plus_today=0,
            plus_to_pro_today=0,
            subscription_expired_today=0,
            expiration_recovery_rate_30d=zero,
        ),
        retention=RetentionMetrics(day_1=zero, day_7=zero, day_30=zero),
    )
