from __future__ import annotations

import argparse
import asyncio
from contextlib import suppress
from dataclasses import dataclass
import logging
from collections.abc import Sequence
import os
import signal
from time import perf_counter

from aiogram import Bot, Dispatcher
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web
from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy import func, select

from app.config import Settings, get_settings
from app.db.models import OutboxEvent
from app.db.session import dispose_engine, measure_pool_wait_ms
from app.db.session import AsyncSessionLocal
from app.logging_config import configure_logging
from app.bot.dispatcher import build_dispatcher
from app.bot.dispatcher import _uses_redis_security_state
from app.repositories.outbox import OUTBOX_DEAD, OUTBOX_FAILED, OUTBOX_PENDING, OUTBOX_PROCESSING, OutboxRepository
from app.runtime.backpressure import BackpressureMonitor, global_backpressure_monitor
from app.runtime.driver_profiling import install_driver_profiling
from app.runtime.webhook_handler import ProfiledSimpleRequestHandler
from app.runtime.webhook_ingress_handler import FastWebhookIngressHandler
from app.runtime.webhook_ingress_queue import WebhookIngressQueue, WebhookIngressQueueError, WebhookIngressQueueSettings
from app.runtime.webhook_profiling import (
    create_webhook_profile_collector_from_env,
    install_aiogram_webhook_profiling,
)
from app.runtime.redis import close_redis_client, create_redis_client, warm_redis_client
from app.runtime.fake_telegram import FakeTelegramSession

logger = logging.getLogger(__name__)
# Container health and webhook endpoints must be reachable inside Docker.
WEBHOOK_BIND_HOST = os.environ.get("WEBHOOK_BIND_HOST", "0.0.0.0")  # nosec B104
WEBHOOK_BIND_PORT = int(os.environ.get("WEBHOOK_BIND_PORT", "8080"))
WEBHOOK_LISTEN_BACKLOG = int(os.environ.get("WEBHOOK_LISTEN_BACKLOG", "4096"))
READY_DB_POOL_WAIT_UNHEALTHY_MS = 200.0
READY_REDIS_LATENCY_UNHEALTHY_MS = 50.0
READY_WORKER_LAG_UNHEALTHY_SECONDS = 120.0
DEFAULT_RUNTIME_COMMAND = "run"
SERVE_WEBHOOK_COMMAND = "serve-webhook"
REGISTER_WEBHOOK_COMMAND = "register-webhook"


@dataclass(frozen=True)
class WebhookRuntimeConfig:
    url: str
    path: str
    secret: str
    request_timeout: int
    max_connections: int
    handle_in_background: bool


def create_dispatcher(*, redis_client: Redis | None = None) -> Dispatcher:
    """Create and configure a dispatcher with all production-relevant routers."""
    return build_dispatcher(redis_client=redis_client)


def create_bot(token: str) -> Bot:
    """Create a bot client from token."""
    settings = get_settings()
    if getattr(settings, "bot_fake_api_enabled", False):
        return Bot(token=token, session=FakeTelegramSession())
    return Bot(token=token)


def create_webhook_ingress_queue(settings: Settings, redis_client: Redis) -> WebhookIngressQueue:
    """Create Redis Stream backed Telegram webhook ingress queue."""
    return WebhookIngressQueue(
        redis_client,
        WebhookIngressQueueSettings(
            stream_key=settings.webhook_ingress_stream_key,
            group_name=settings.webhook_ingress_group_name,
            dead_letter_key=settings.webhook_ingress_dead_letter_key,
            dedupe_key_prefix=settings.webhook_ingress_dedupe_key_prefix,
            metrics_key_prefix=settings.webhook_ingress_metrics_key_prefix,
            dedupe_ttl_seconds=settings.telegram_duplicate_update_ttl_seconds,
            processing_lag_sample_size=settings.webhook_ingress_processing_lag_sample_size,
        ),
    )


def build_parser() -> argparse.ArgumentParser:
    """Build the bot runtime CLI parser."""
    parser = argparse.ArgumentParser(description="Run the Deutsch Trainer Bot runtime.")
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser(DEFAULT_RUNTIME_COMMAND, help="Start the configured bot runtime.")
    subparsers.add_parser(
        SERVE_WEBHOOK_COMMAND,
        help="Serve webhook HTTP without mutating Telegram webhook state.",
    )
    subparsers.add_parser(
        REGISTER_WEBHOOK_COMMAND,
        help="Register the Telegram webhook and exit.",
    )
    parser.set_defaults(command=DEFAULT_RUNTIME_COMMAND)
    return parser


async def health_check(_request: web.Request) -> web.Response:
    """Return a minimal container health response."""
    return web.json_response({"status": "ok"})


async def readiness_check(request: web.Request) -> web.Response:
    """Return readiness after checking runtime dependencies."""

    checks: dict[str, object] = {}
    status_code = 200
    status_code = _merge_status(status_code, await _database_readiness(checks))
    status_code = _merge_status(status_code, await _redis_readiness(request, checks))
    status_code = _merge_status(status_code, _backpressure_readiness(request, checks))

    if request.app.get("outbox_readiness_enabled", False):
        status_code = _merge_status(status_code, await _outbox_readiness(checks))
    if request.app.get("webhook_ingress_readiness_enabled", False):
        status_code = _merge_status(status_code, await _webhook_ingress_readiness(request, checks))

    status = "ok" if status_code == 200 else "unavailable"
    return web.json_response({"status": status, "checks": checks}, status=status_code)


async def _database_readiness(checks: dict[str, object]) -> int:
    try:
        db_wait_ms = await measure_pool_wait_ms()
        db_status = "ok" if db_wait_ms <= READY_DB_POOL_WAIT_UNHEALTHY_MS else "saturated"
        checks["database"] = {"status": db_status, "pool_wait_ms": round(db_wait_ms, 3)}
        return 200 if db_status == "ok" else 503
    except Exception as exc:
        logger.warning("readiness database check failed: %s", exc.__class__.__name__)
        checks["database"] = {"status": "unavailable"}
        return 503


async def _redis_readiness(request: web.Request, checks: dict[str, object]) -> int:
    redis_client = request.app.get("redis_client")
    if redis_client is None:
        return 200
    redis_started = perf_counter()
    try:
        await redis_client.ping()
        latency_ms = (perf_counter() - redis_started) * 1000
        redis_status = "ok" if latency_ms <= READY_REDIS_LATENCY_UNHEALTHY_MS else "saturated"
        checks["redis"] = {"status": redis_status, "latency_ms": round(latency_ms, 3)}
        return 200 if redis_status == "ok" else 503
    except RedisError as exc:
        logger.warning("readiness redis check failed: %s", exc.__class__.__name__)
        checks["redis"] = {"status": "unavailable"}
        return 503


def _backpressure_readiness(request: web.Request, checks: dict[str, object]) -> int:
    monitor = request.app.get("backpressure_monitor")
    if not isinstance(monitor, BackpressureMonitor):
        return 200
    snapshot = monitor.snapshot()
    checks["backpressure"] = {
        "status": "saturated" if snapshot.saturated else "ok",
        "limit": snapshot.limit,
        "in_flight": snapshot.in_flight,
        "available": snapshot.available,
        "rejected_total": snapshot.rejected_total,
        "seconds_since_last_rejection": _rounded_or_none(snapshot.seconds_since_last_rejection),
    }
    return 503 if snapshot.saturated else 200


async def _outbox_readiness(checks: dict[str, object]) -> int:
    try:
        async with AsyncSessionLocal() as db:
            outbox_repo = OutboxRepository()
            lag_seconds = await outbox_repo.pending_lag_seconds(db)
            pending_count = await _outbox_status_count(db, OUTBOX_PENDING)
            processing_count = await _outbox_status_count(db, OUTBOX_PROCESSING)
            failed_count = await _outbox_status_count(db, OUTBOX_FAILED)
            dead_count = await _outbox_status_count(db, OUTBOX_DEAD)
        worker_status = _worker_status(lag_seconds, dead_count)
        checks["outbox_worker"] = {
            "status": worker_status,
            "lag_seconds": round(lag_seconds, 3),
            "pending": pending_count,
            "processing": processing_count,
            "failed": failed_count,
            "dead": dead_count,
        }
        return 200 if worker_status == "ok" else 503
    except Exception as exc:
        logger.warning("readiness outbox check failed: %s", exc.__class__.__name__)
        checks["outbox_worker"] = {"status": "unavailable"}
        return 503


async def _webhook_ingress_readiness(request: web.Request, checks: dict[str, object]) -> int:
    queue = request.app.get("webhook_ingress_queue")
    settings = get_settings()
    if not isinstance(queue, WebhookIngressQueue):
        checks["webhook_ingress"] = {"status": "unavailable"}
        return 503
    try:
        stats = await queue.stats()
    except WebhookIngressQueueError as exc:
        logger.warning("readiness webhook ingress check failed: %s", exc)
        checks["webhook_ingress"] = {"status": "unavailable"}
        return 503

    if stats.dead_letter_length > 0:
        status = "unavailable"
    elif stats.oldest_lag_ms > settings.webhook_ingress_queue_lag_unhealthy_ms:
        status = "saturated"
    else:
        status = "ok"
    checks["webhook_ingress"] = {
        "status": status,
        "queue_depth": stats.queue_depth,
        "stream_length": stats.stream_length,
        "pending": stats.pending,
        "lag": stats.lag,
        "oldest_lag_ms": stats.oldest_lag_ms,
        "dead_letter_length": stats.dead_letter_length,
        "processed_total": stats.processed_total,
        "failed_total": stats.failed_total,
        "dead_total": stats.dead_total,
    }
    return 200 if status == "ok" else 503


async def _outbox_status_count(db, status: str) -> int:
    query = select(func.count()).select_from(OutboxEvent).where(OutboxEvent.status == status)
    return int((await db.scalar(query)) or 0)


def _worker_status(lag_seconds: float, dead_count: int) -> str:
    if lag_seconds <= READY_WORKER_LAG_UNHEALTHY_SECONDS and dead_count == 0:
        return "ok"
    return "unavailable"


def _merge_status(current: int, new: int) -> int:
    return 503 if current == 503 or new == 503 else 200


def _rounded_or_none(value: float | None) -> float | None:
    return None if value is None else round(value, 3)


def create_webhook_app(
    dispatcher: Dispatcher,
    bot: Bot,
    *,
    webhook_path: str,
    webhook_secret: str,
    handle_in_background: bool,
    redis_client: Redis | None = None,
) -> web.Application:
    """Create an aiohttp app that forwards Telegram webhook updates to aiogram."""
    settings = get_settings()
    app = web.Application()
    webhook_profiler = create_webhook_profile_collector_from_env()
    app["redis_client"] = redis_client
    app["backpressure_monitor"] = global_backpressure_monitor
    app["outbox_readiness_enabled"] = True
    app.router.add_get("/health", health_check)
    app.router.add_get("/ready", readiness_check)
    if webhook_profiler.enabled and settings.webhook_ingress_backend == WebhookIngressBackend.direct:
        install_aiogram_webhook_profiling()
        install_driver_profiling()
        webhook_profiler.start()
        app["webhook_profiler"] = webhook_profiler
        app.on_shutdown.append(_close_webhook_profiler)
    if settings.webhook_ingress_backend == WebhookIngressBackend.redis_stream:
        if redis_client is None:
            raise RuntimeError("Redis client is required for WEBHOOK_INGRESS_BACKEND=redis_stream")
        queue = create_webhook_ingress_queue(settings, redis_client)
        app["webhook_ingress_queue"] = queue
        app["webhook_ingress_readiness_enabled"] = True
        app.on_startup.append(_ensure_webhook_ingress_group)
        FastWebhookIngressHandler(queue=queue, secret_token=webhook_secret).register(app, path=webhook_path)
    else:
        request_handler_cls = SimpleRequestHandler
        request_handler_kwargs: dict[str, object] = {}
        if webhook_profiler.enabled:
            request_handler_cls = ProfiledSimpleRequestHandler
            request_handler_kwargs["profiler"] = webhook_profiler
        request_handler_cls(
            dispatcher=dispatcher,
            bot=bot,
            handle_in_background=handle_in_background,
            secret_token=webhook_secret,
            **request_handler_kwargs,
        ).register(app, path=webhook_path)
    setup_application(app, dispatcher, bot=bot)
    return app


async def _ensure_webhook_ingress_group(app: web.Application) -> None:
    queue = app.get("webhook_ingress_queue")
    if isinstance(queue, WebhookIngressQueue):
        await queue.ensure_group()


def create_webhook_config(settings) -> WebhookRuntimeConfig:
    """Build validated webhook runtime config from settings."""
    if not settings.webhook_mode_enabled:
        raise RuntimeError("Webhook mode must be fully configured for this command")
    return WebhookRuntimeConfig(
        url=settings.telegram_webhook_url or "",
        path=settings.telegram_webhook_path,
        secret=settings.telegram_webhook_secret.get_secret_value()
        if settings.telegram_webhook_secret
        else "",
        request_timeout=settings.bot_max_request_timeout,
        max_connections=settings.telegram_webhook_max_connections,
        handle_in_background=getattr(settings, "telegram_webhook_handle_in_background", True),
    )


async def register_webhook(
    bot: Bot,
    *,
    config: WebhookRuntimeConfig,
) -> None:
    """Register the Telegram webhook and reset pending updates."""
    logger.info("Registering webhook for path=%s", config.path)
    await bot.delete_webhook(drop_pending_updates=True)
    await bot.set_webhook(
        url=f"{config.url}{config.path}",
        secret_token=config.secret,
        request_timeout=config.request_timeout,
        max_connections=config.max_connections,
    )


async def run_webhook(
    bot: Bot,
    dispatcher: Dispatcher,
    *,
    config: WebhookRuntimeConfig,
    redis_client: Redis | None,
) -> None:
    """Run Telegram webhook receiver on the container HTTP port."""
    app = create_webhook_app(
        dispatcher,
        bot,
        webhook_path=config.path,
        webhook_secret=config.secret,
        handle_in_background=config.handle_in_background,
        redis_client=redis_client,
    )
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(
        runner,
        host=WEBHOOK_BIND_HOST,
        port=WEBHOOK_BIND_PORT,
        backlog=WEBHOOK_LISTEN_BACKLOG,
    )
    try:
        await site.start()
        logger.info("Webhook server is listening on %s:%s", WEBHOOK_BIND_HOST, WEBHOOK_BIND_PORT)
        await _wait_for_shutdown()
    finally:
        await runner.cleanup()


async def run_bot(command: str = DEFAULT_RUNTIME_COMMAND) -> None:
    """Run minimal bot runtime scaffold."""
    settings = get_settings()
    settings.require_production_secrets()
    configure_logging(settings.log_level)

    if not settings.bot_token:
        raise RuntimeError("BOT_TOKEN must be set for runtime execution")

    redis_client = None
    bot = create_bot(settings.bot_token.get_secret_value())

    try:
        if command == REGISTER_WEBHOOK_COMMAND:
            await register_webhook(
                bot,
                config=create_webhook_config(settings),
            )
            return

        redis_client = create_redis_client(settings) if _uses_redis_runtime(settings) else None
        await _warm_redis_runtime(settings, redis_client)
        dp = create_dispatcher(redis_client=redis_client)
        await _run_configured_mode(command, settings=settings, bot=bot, dispatcher=dp, redis_client=redis_client)
    finally:
        await bot.session.close()
        await close_redis_client(redis_client)
        await dispose_engine()


async def _warm_redis_runtime(settings: Settings, redis_client: Redis | None) -> None:
    if redis_client is None or not _uses_redis_security_state(settings):
        return
    warmup_count = min(settings.redis_warmup_connections, settings.redis_max_connections)
    warmup = await warm_redis_client(redis_client, connection_count=warmup_count)
    logger.info(
        "Redis pool warmup completed: requested=%s succeeded=%s failed=%s",
        warmup["requested"],
        warmup["succeeded"],
        warmup["failed"],
    )


async def _run_configured_mode(
    command: str,
    *,
    settings: Settings,
    bot: Bot,
    dispatcher: Dispatcher,
    redis_client: Redis | None,
) -> None:
    if command == SERVE_WEBHOOK_COMMAND or settings.webhook_mode_enabled:
        mode_label = "webhook server" if command == SERVE_WEBHOOK_COMMAND else "webhook"
        logger.info("Starting %s mode with path=%s", mode_label, settings.telegram_webhook_path)
        await run_webhook(
            bot=bot,
            dispatcher=dispatcher,
            config=create_webhook_config(settings),
            redis_client=redis_client,
        )
        return
    if settings.bot_polling_enabled:
        logger.info("Starting polling mode")
        await dispatcher.start_polling(bot, request_timeout=settings.bot_max_request_timeout)
        return
    raise RuntimeError("No bot runtime mode is enabled")


async def _wait_for_shutdown() -> None:
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for item in (signal.SIGINT, signal.SIGTERM):
        with suppress(NotImplementedError, RuntimeError):
            loop.add_signal_handler(item, stop_event.set)
    await stop_event.wait()


async def _close_webhook_profiler(app: web.Application) -> None:
    profiler = app.get("webhook_profiler")
    if profiler is None:
        return
    profiler.close()


def _uses_redis_runtime(settings) -> bool:
    ingress_backend = getattr(settings, "webhook_ingress_backend", WebhookIngressBackend.direct)
    return (
        _uses_redis_security_state(settings)
        or ingress_backend == WebhookIngressBackend.redis_stream
        or bool(getattr(settings, "local_catalog_cache_enabled", False))
        or bool(getattr(settings, "training_answer_cache_enabled", False))
        or bool(getattr(settings, "training_answer_write_behind_enabled", False))
    )


def main(argv: Sequence[str] | None = None) -> None:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    asyncio.run(run_bot(args.command))


if __name__ == "__main__":
    main()
