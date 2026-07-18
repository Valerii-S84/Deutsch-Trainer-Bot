from __future__ import annotations

from math import ceil
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.bot.dispatcher import _uses_redis_security_state
from app.bot.middlewares.security import SecurityMiddleware
from app.bot.texts import RATE_LIMIT_HIT_TEXT
from app.config import Settings
from app.security.rate_limits import (
    ACTION_PAYMENT_START,
    ACTION_START,
    DuplicateUpdateGuard,
    InMemoryRateLimiter,
    RateLimitRule,
    RedisDuplicateUpdateGuard,
    RedisRateLimiter,
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


class FakeRedis:
    def __init__(self) -> None:
        self.now = 0.0
        self.values: dict[str, float] = {}
        self.zsets: dict[str, list[tuple[int, str]]] = {}

    async def time(self):
        seconds = int(self.now)
        microseconds = int((self.now - seconds) * 1_000_000)
        return seconds, microseconds

    async def set(self, key: str, _value: str, *, ex: int, nx: bool):
        self._drop_expired_values()
        if nx and key in self.values:
            return None
        self.values[key] = self.now + ex
        return True

    async def eval(self, _script, _numkeys, key, now_ms, window_ms, limit, _ttl_seconds, member):
        bucket = [
            (score, value)
            for score, value in self.zsets.get(key, [])
            if score > int(now_ms) - int(window_ms)
        ]
        if len(bucket) >= int(limit):
            oldest_score = min(score for score, _value in bucket)
            retry_ms = int(window_ms) - (int(now_ms) - oldest_score)
            return [0, max(1, ceil(retry_ms / 1000))]
        bucket.append((int(now_ms), str(member)))
        self.zsets[key] = bucket
        return [1, 0]

    def advance(self, seconds: float) -> None:
        self.now += seconds

    def _drop_expired_values(self) -> None:
        expired = [key for key, expires_at in self.values.items() if expires_at <= self.now]
        for key in expired:
            self.values.pop(key, None)


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
async def test_redis_duplicate_update_guard_rejects_seen_update_until_ttl_expires() -> None:
    redis = FakeRedis()
    guard = RedisDuplicateUpdateGuard(redis, ttl_seconds=30)

    assert await guard.accept(5001) is True
    assert await guard.accept(5001) is False

    redis.advance(31)
    assert await guard.accept(5001) is True


@pytest.mark.asyncio
async def test_redis_rate_limiter_blocks_until_window_expires() -> None:
    redis = FakeRedis()
    limiter = RedisRateLimiter(
        redis,
        {ACTION_START: RateLimitRule(ACTION_START, limit=2, window_seconds=10)},
    )

    assert (await limiter.check(action=ACTION_START, identity="user:1")).allowed is True
    assert (await limiter.check(action=ACTION_START, identity="user:1")).allowed is True

    blocked = await limiter.check(action=ACTION_START, identity="user:1")
    assert blocked.allowed is False
    assert blocked.retry_after_seconds == 10

    redis.advance(10)
    assert (await limiter.check(action=ACTION_START, identity="user:1")).allowed is True


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


def test_webhook_mode_does_not_fall_back_to_polling_when_incomplete() -> None:
    with pytest.raises(ValueError, match="TELEGRAM_WEBHOOK_URL"):
        Settings(app_env="development", bot_webhook_enabled=True, bot_polling_enabled=True)


def test_runtime_mode_requires_webhook_or_polling_enabled() -> None:
    with pytest.raises(ValueError, match="BOT_WEBHOOK_ENABLED or BOT_POLLING_ENABLED"):
        Settings(bot_polling_enabled=False)


def test_hardening_runtime_defaults_are_bounded() -> None:
    settings = Settings()

    assert settings.telegram_webhook_max_connections == 40
    assert settings.bot_global_in_flight_limit == 512
    assert settings.effective_bot_in_flight_limit == 512
    assert settings.db_pool_size == 20
    assert settings.db_max_overflow == 10
    assert settings.db_pool_timeout == 5.0
    assert settings.db_pool_recycle == 1800
    assert settings.db_pool_pre_ping is True


def test_pgbouncer_backend_clamps_effective_in_flight_limit_below_client_cap() -> None:
    settings = Settings(
        DB_CONNECTION_BACKEND="pgbouncer_transaction",
        DB_PGBOUNCER_MAX_CLIENT_CONN=200,
        DB_PGBOUNCER_CLIENT_HEADROOM=32,
    )

    assert settings.bot_global_in_flight_limit == 512
    assert settings.shared_bot_in_flight_limit == 168
    assert settings.effective_bot_in_flight_limit == 168


def test_multi_instance_pgbouncer_budget_exposes_shared_and_local_limits() -> None:
    settings = Settings(
        DB_CONNECTION_BACKEND="pgbouncer_transaction",
        DB_PGBOUNCER_MAX_CLIENT_CONN=200,
        DB_PGBOUNCER_CLIENT_HEADROOM=32,
        DB_APP_REPLICA_COUNT=4,
        DB_WORKER_REPLICA_COUNT=2,
        DB_WORKER_CLIENT_BUDGET_PER_REPLICA=5,
    )

    assert settings.shared_bot_in_flight_limit == 158
    assert settings.effective_bot_in_flight_limit == 39
    assert settings.cluster_app_db_client_budget == 158
    assert settings.cluster_worker_db_client_budget == 10
    assert settings.cluster_total_pgbouncer_client_budget == 200


def test_pgbouncer_reused_pool_budget_rejects_cluster_overcommit() -> None:
    with pytest.raises(ValueError, match="PgBouncer client budget exceeds"):
        Settings(
            DB_CONNECTION_BACKEND="pgbouncer_transaction",
            DB_PGBOUNCER_REUSE_APP_CONNECTIONS=True,
            DB_PGBOUNCER_MAX_CLIENT_CONN=200,
            DB_PGBOUNCER_CLIENT_HEADROOM=32,
            DB_APP_REPLICA_COUNT=6,
            DB_WORKER_REPLICA_COUNT=2,
        )


def test_pgbouncer_worker_budget_must_leave_capacity_for_app_replicas() -> None:
    with pytest.raises(ValueError, match="worker client budget leaves no capacity"):
        Settings(
            DB_CONNECTION_BACKEND="pgbouncer_transaction",
            DB_PGBOUNCER_MAX_CLIENT_CONN=50,
            DB_PGBOUNCER_CLIENT_HEADROOM=10,
            DB_WORKER_REPLICA_COUNT=8,
            DB_WORKER_CLIENT_BUDGET_PER_REPLICA=5,
        )


def test_production_security_state_cannot_use_process_local_backend() -> None:
    with pytest.raises(ValueError, match="SECURITY_STATE_BACKEND"):
        Settings(app_env="production", SECURITY_STATE_BACKEND="in_memory")


def test_auto_security_state_uses_redis_outside_development() -> None:
    assert _uses_redis_security_state(Settings(app_env="development")) is False
    assert _uses_redis_security_state(Settings(app_env="staging")) is True


def test_release_one_launch_config_defaults_are_locked() -> None:
    settings = Settings()

    assert settings.free_daily_question_limit == 5
    assert settings.plus_daily_question_limit == 25
    assert settings.pro_daily_question_limit == 100
    assert settings.paywall_cooldown_policy == "none"
    assert settings.plus_price_stars == "10"
    assert settings.pro_price_stars == "20"
    assert settings.plus_duration_days == 30
    assert settings.pro_duration_days == 90
    assert settings.telegram_stars_mode == "test"
    assert settings.enabled_cefr_levels == ("A1", "A2", "B1", "B2", "C1")
    assert settings.catalog_source_path == "ProductionQuizBank"


def test_enabled_cefr_levels_accept_c2_but_default_excludes_it() -> None:
    settings = Settings(ENABLED_CEFR_LEVELS="A1,B2,C2")

    assert settings.enabled_cefr_levels == ("A1", "B2", "C2")


def test_active_catalog_id_cannot_be_blank_when_set() -> None:
    with pytest.raises(ValueError, match="ACTIVE_CATALOG_ID"):
        Settings(ACTIVE_CATALOG_ID=" ")


def test_production_secrets_do_not_require_legacy_quiz_bank_credentials() -> None:
    settings = Settings(
        app_env="production",
        bot_webhook_enabled=True,
        bot_token="123:ABC",
        telegram_webhook_url="https://bot.example.test",
        telegram_webhook_secret="webhook-secret",
        TELEGRAM_STARS_MODE="prod",
    )

    settings.require_production_secrets()


def test_paywall_cooldown_policy_is_none_for_release_one() -> None:
    with pytest.raises(ValueError, match="PAYWALL_COOLDOWN_POLICY"):
        Settings(PAYWALL_COOLDOWN_POLICY="daily_cap")


def test_production_requires_telegram_stars_prod_mode() -> None:
    settings = Settings(
        app_env="production",
        bot_webhook_enabled=True,
        bot_token="123:ABC",
        telegram_webhook_url="https://bot.example.test",
        telegram_webhook_secret="webhook-secret",
        quiz_bank_edge_api_key="edge-key",
        quiz_bank_consumer_id="deutsch-trainer-bot",
        quiz_bank_consumer_api_key="consumer-key",
        TELEGRAM_STARS_MODE="test",
    )

    with pytest.raises(ValueError, match="TELEGRAM_STARS_MODE"):
        settings.require_production_secrets()
