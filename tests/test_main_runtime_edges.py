from __future__ import annotations

from unittest.mock import AsyncMock

from aiohttp import web
import pytest
from pydantic import SecretStr
from redis.exceptions import RedisError

import app.main
from app.runtime.backpressure import BackpressureMonitor


@pytest.mark.asyncio
async def test_database_readiness_reports_saturation_and_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    async def saturated_wait() -> float:
        return app.main.READY_DB_POOL_WAIT_UNHEALTHY_MS + 1

    checks: dict[str, object] = {}
    monkeypatch.setattr(app.main, "measure_pool_wait_ms", saturated_wait)

    assert await app.main._database_readiness(checks) == 503
    assert checks["database"] == {"status": "saturated", "pool_wait_ms": 201.0}

    async def broken_wait() -> float:
        raise RuntimeError("db down")

    checks = {}
    monkeypatch.setattr(app.main, "measure_pool_wait_ms", broken_wait)

    assert await app.main._database_readiness(checks) == 503
    assert checks["database"] == {"status": "unavailable"}


@pytest.mark.asyncio
async def test_redis_readiness_reports_saturation_and_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    application = web.Application()
    application["redis_client"] = _RedisOk()
    request = type("Request", (), {"app": application})()
    ticks = iter([0.0, 0.1])
    monkeypatch.setattr(app.main, "perf_counter", lambda: next(ticks))
    checks: dict[str, object] = {}

    assert await app.main._redis_readiness(request, checks) == 503
    assert checks["redis"] == {"status": "saturated", "latency_ms": 100.0}

    application["redis_client"] = _RedisDown()
    checks = {}
    monkeypatch.setattr(app.main, "perf_counter", lambda: 0.0)

    assert await app.main._redis_readiness(request, checks) == 503
    assert checks["redis"] == {"status": "unavailable"}


def test_backpressure_readiness_reports_recent_saturation() -> None:
    monitor = BackpressureMonitor()
    monitor.configure(limit=1)
    monitor.acquired()
    application = web.Application()
    application["backpressure_monitor"] = monitor
    request = type("Request", (), {"app": application})()
    checks: dict[str, object] = {}

    assert app.main._backpressure_readiness(request, checks) == 503
    assert checks["backpressure"]["status"] == "saturated"  # type: ignore[index]
    assert checks["backpressure"]["in_flight"] == 1  # type: ignore[index]


@pytest.mark.asyncio
async def test_outbox_readiness_reports_worker_lag_and_dead_events(monkeypatch: pytest.MonkeyPatch) -> None:
    async def status_count(_db, status: str) -> int:
        return 1 if status == app.main.OUTBOX_DEAD else 0

    monkeypatch.setattr(app.main, "AsyncSessionLocal", lambda: _SessionContext())
    monkeypatch.setattr(app.main, "OutboxRepository", _LaggedOutboxRepo)
    monkeypatch.setattr(app.main, "_outbox_status_count", status_count)
    checks: dict[str, object] = {}

    assert await app.main._outbox_readiness(checks) == 503
    assert checks["outbox_worker"]["status"] == "unavailable"  # type: ignore[index]
    assert checks["outbox_worker"]["dead"] == 1  # type: ignore[index]


@pytest.mark.asyncio
async def test_webhook_ingress_readiness_reports_dead_letter_and_queue_lag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(app.main, "WebhookIngressQueue", _QueueStub)
    monkeypatch.setattr(app.main, "get_settings", lambda: _SettingsStub())

    application = web.Application()
    application["webhook_ingress_queue"] = _QueueStub(_webhook_stats(dead_letter_length=1, oldest_lag_ms=0))
    request = type("Request", (), {"app": application})()
    checks: dict[str, object] = {}

    assert await app.main._webhook_ingress_readiness(request, checks) == 503
    assert checks["webhook_ingress"]["status"] == "unavailable"  # type: ignore[index]

    application["webhook_ingress_queue"] = _QueueStub(_webhook_stats(dead_letter_length=0, oldest_lag_ms=130_000))
    checks = {}

    assert await app.main._webhook_ingress_readiness(request, checks) == 503
    assert checks["webhook_ingress"]["status"] == "saturated"  # type: ignore[index]


@pytest.mark.asyncio
async def test_run_configured_mode_routes_polling_and_rejects_disabled_runtime() -> None:
    dispatcher = _DispatcherStub()
    settings = type(
        "Settings",
        (),
        {"webhook_mode_enabled": False, "bot_polling_enabled": True, "bot_max_request_timeout": 15},
    )()
    bot = object()

    await app.main._run_configured_mode("run", settings=settings, bot=bot, dispatcher=dispatcher, redis_client=None)

    dispatcher.start_polling.assert_awaited_once_with(bot, request_timeout=15)

    disabled = type("Settings", (), {"webhook_mode_enabled": False, "bot_polling_enabled": False})()
    with pytest.raises(RuntimeError, match="No bot runtime mode"):
        await app.main._run_configured_mode("run", settings=disabled, bot=object(), dispatcher=dispatcher, redis_client=None)


@pytest.mark.asyncio
async def test_warm_redis_runtime_respects_configured_connection_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    warm = AsyncMock(return_value={"requested": 3, "succeeded": 3, "failed": 0})
    monkeypatch.setattr(app.main, "warm_redis_client", warm)
    settings = type(
        "Settings",
        (),
        {"redis_warmup_connections": 10, "redis_max_connections": 3, "security_state_backend": "redis"},
    )()
    redis_client = object()

    await app.main._warm_redis_runtime(settings, redis_client=redis_client)

    warm.assert_awaited_once_with(redis_client, connection_count=3)


def test_create_webhook_config_and_redis_runtime_decisions() -> None:
    settings = type(
        "Settings",
        (),
        {
            "webhook_mode_enabled": True,
            "telegram_webhook_url": "https://example.test",
            "telegram_webhook_path": "/telegram/webhook",
            "telegram_webhook_secret": SecretStr("secret"),
            "bot_max_request_timeout": 30,
            "telegram_webhook_max_connections": 40,
            "telegram_webhook_handle_in_background": False,
            "webhook_ingress_backend": app.main.WebhookIngressBackend.direct,
            "app_env": "development",
            "security_state_backend": "in_memory",
            "local_catalog_cache_enabled": False,
            "training_answer_cache_enabled": False,
            "training_answer_write_behind_enabled": False,
        },
    )()

    config = app.main.create_webhook_config(settings)

    assert config.url == "https://example.test"
    assert config.path == "/telegram/webhook"
    assert config.secret == "secret"
    assert config.handle_in_background is False
    assert app.main._uses_redis_runtime(settings) is False

    settings.webhook_ingress_backend = app.main.WebhookIngressBackend.redis_stream
    assert app.main._uses_redis_runtime(settings) is True


def test_webhook_config_fails_fast_when_runtime_is_not_fully_configured() -> None:
    settings = type("Settings", (), {"webhook_mode_enabled": False})()

    with pytest.raises(RuntimeError, match="Webhook mode must be fully configured"):
        app.main.create_webhook_config(settings)

    assert app.main._worker_status(0.0, 0) == "ok"
    assert app.main._worker_status(app.main.READY_WORKER_LAG_UNHEALTHY_SECONDS + 1, 0) == "unavailable"
    assert app.main._worker_status(0.0, 1) == "unavailable"


class _RedisOk:
    async def ping(self) -> bool:
        return True


class _RedisDown:
    async def ping(self) -> bool:
        raise RedisError("redis down")


class _SessionContext:
    async def __aenter__(self):
        return object()

    async def __aexit__(self, exc_type, exc, tb) -> None:  # type: ignore[override]
        return None


class _LaggedOutboxRepo:
    async def pending_lag_seconds(self, _db) -> float:
        return app.main.READY_WORKER_LAG_UNHEALTHY_SECONDS + 1


class _QueueStub:
    def __init__(self, stats) -> None:
        self._stats = stats

    async def stats(self):
        return self._stats


class _SettingsStub:
    webhook_ingress_queue_lag_unhealthy_ms = 120_000


class _DispatcherStub:
    def __init__(self) -> None:
        self.start_polling = AsyncMock()


def _webhook_stats(*, dead_letter_length: int, oldest_lag_ms: int):
    return type(
        "WebhookStats",
        (),
        {
            "queue_depth": 5,
            "stream_length": 10,
            "pending": 2,
            "lag": 1,
            "oldest_lag_ms": oldest_lag_ms,
            "dead_letter_length": dead_letter_length,
            "processed_total": 100,
            "failed_total": 1,
            "dead_total": dead_letter_length,
        },
    )()
