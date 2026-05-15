from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.bot.middlewares.security import SecurityMiddleware
from app.bot.texts import RATE_LIMIT_HIT_TEXT
from app.config import Settings
from app.security.rate_limits import (
    ACTION_PAYMENT_START,
    ACTION_START,
    DuplicateUpdateGuard,
    InMemoryRateLimiter,
    RateLimitRule,
)


class MutableClock:
    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


class FakeCallback:
    def __init__(self, data: str, user_id: int = 111) -> None:
        self.data = data
        self.from_user = SimpleNamespace(id=user_id)
        self.answer = AsyncMock()


def _update(update_id: int, callback: FakeCallback):
    return SimpleNamespace(update_id=update_id, callback_query=callback)


def test_rate_limiter_blocks_until_window_expires() -> None:
    clock = MutableClock()
    limiter = InMemoryRateLimiter(
        {ACTION_START: RateLimitRule(ACTION_START, limit=2, window_seconds=10)},
        time_func=clock,
    )

    assert limiter.check(action=ACTION_START, identity="user:1").allowed is True
    assert limiter.check(action=ACTION_START, identity="user:1").allowed is True

    blocked = limiter.check(action=ACTION_START, identity="user:1")
    assert blocked.allowed is False
    assert blocked.retry_after_seconds == 10

    clock.advance(10)
    assert limiter.check(action=ACTION_START, identity="user:1").allowed is True


def test_duplicate_update_guard_rejects_seen_update_until_ttl_expires() -> None:
    clock = MutableClock()
    guard = DuplicateUpdateGuard(ttl_seconds=30, time_func=clock)

    assert guard.accept(5001) is True
    assert guard.accept(5001) is False

    clock.advance(31)
    assert guard.accept(5001) is True


@pytest.mark.asyncio
async def test_security_middleware_drops_duplicate_update() -> None:
    handled: list[int] = []
    middleware = SecurityMiddleware(
        rate_limit_enabled=False,
        duplicate_guard=DuplicateUpdateGuard(ttl_seconds=30),
    )

    async def handler(event, data):
        handled.append(event.update_id)
        return "ok"

    callback = FakeCallback("payment:plan:plus")
    first = await middleware(handler, _update(7001, callback), {})
    second = await middleware(handler, _update(7001, callback), {})

    assert first == "ok"
    assert second is None
    assert handled == [7001]


@pytest.mark.asyncio
async def test_security_middleware_rate_limits_payment_start_callback() -> None:
    limiter = InMemoryRateLimiter(
        {ACTION_PAYMENT_START: RateLimitRule(ACTION_PAYMENT_START, limit=1, window_seconds=60)},
    )
    middleware = SecurityMiddleware(
        rate_limiter=limiter,
        duplicate_guard=DuplicateUpdateGuard(ttl_seconds=30),
    )
    handled: list[int] = []

    async def handler(event, data):
        handled.append(event.update_id)
        return "ok"

    first_callback = FakeCallback("payment:plan:plus")
    second_callback = FakeCallback("payment:plan:plus")
    await middleware(handler, _update(8001, first_callback), {})
    result = await middleware(handler, _update(8002, second_callback), {})

    assert result is None
    assert handled == [8001]
    second_callback.answer.assert_awaited_once_with(RATE_LIMIT_HIT_TEXT, show_alert=False)


def test_webhook_mode_requires_https_outside_development() -> None:
    with pytest.raises(ValueError, match="HTTPS"):
        Settings(
            app_env="staging",
            bot_webhook_enabled=True,
            telegram_webhook_url="http://bot.example.test",
            telegram_webhook_secret="webhook-secret",
        )


def test_webhook_mode_requires_secret_outside_development() -> None:
    with pytest.raises(ValueError, match="TELEGRAM_WEBHOOK_SECRET"):
        Settings(
            app_env="staging",
            bot_webhook_enabled=True,
            telegram_webhook_url="https://bot.example.test",
        )
