"""Dispatcher factory for aiogram entrypoint."""

from __future__ import annotations

from aiogram import Dispatcher
from redis.asyncio import Redis

from app.bot.middlewares import BackpressureMiddleware, LoggingMiddleware, SecurityMiddleware
from app.bot.routers import build_root_router
from app.config import AppEnvironment, Settings, get_settings
from app.runtime.admission import LocalAdmissionController, RedisAdmissionController
from app.runtime.redis import get_or_create_shared_redis_client
from app.security.rate_limits import (
    DuplicateUpdateGuard,
    InMemoryRateLimiter,
    RedisDuplicateUpdateGuard,
    RedisRateLimiter,
)


def create_dispatcher(settings: Settings | None = None, *, redis_client: Redis | None = None) -> Dispatcher:
    """Create aiogram dispatcher with middleware and full router graph."""
    settings = settings or get_settings()
    dispatcher = Dispatcher()
    runtime_redis_client = _runtime_redis_client(settings, redis_client=redis_client)
    rate_limiter, duplicate_guard = _security_state(settings, redis_client=runtime_redis_client)
    dispatcher.include_router(build_root_router())
    dispatcher.update.middleware(
        BackpressureMiddleware(
            in_flight_limit=settings.effective_bot_in_flight_limit,
            acquire_timeout_seconds=settings.bot_global_in_flight_timeout_seconds,
            admission_controller=_admission_controller(
                settings,
                redis_client=runtime_redis_client,
            ),
        ),
    )
    dispatcher.update.middleware(
        SecurityMiddleware(
            rate_limiter=rate_limiter,
            duplicate_guard=duplicate_guard,
            rate_limit_enabled=settings.security_rate_limit_enabled,
        ),
    )
    dispatcher.update.middleware(LoggingMiddleware())
    return dispatcher


def build_dispatcher(settings: Settings | None = None, *, redis_client: Redis | None = None) -> Dispatcher:
    """Backward-compatible builder name used by existing runtime entrypoints/tests."""
    return create_dispatcher(settings, redis_client=redis_client)


def _security_state(settings: Settings, *, redis_client: Redis | None = None):
    if _uses_redis_security_state(settings):
        redis_client = redis_client or get_or_create_shared_redis_client(settings)
        rate_limiter = RedisRateLimiter(redis_client)
        if settings.db_app_replica_count > 1:
            duplicate_guard = RedisDuplicateUpdateGuard(
                redis_client,
                ttl_seconds=settings.telegram_duplicate_update_ttl_seconds,
            )
        else:
            duplicate_guard = DuplicateUpdateGuard(
                ttl_seconds=settings.telegram_duplicate_update_ttl_seconds,
            )
        return rate_limiter, duplicate_guard
    return (
        InMemoryRateLimiter(),
        DuplicateUpdateGuard(ttl_seconds=settings.telegram_duplicate_update_ttl_seconds),
    )


def _uses_redis_security_state(settings: Settings) -> bool:
    if settings.security_state_backend == "redis":
        return True
    if settings.security_state_backend == "in_memory":
        return False
    return settings.app_env != AppEnvironment.development


def _runtime_redis_client(settings: Settings, *, redis_client: Redis | None = None) -> Redis | None:
    if redis_client is not None:
        return redis_client
    if _uses_redis_security_state(settings):
        return get_or_create_shared_redis_client(settings)
    return None


def _admission_controller(settings: Settings, *, redis_client: Redis | None = None):
    if redis_client is not None and settings.db_app_replica_count > 1:
        return RedisAdmissionController(
            redis_client,
            limit=settings.shared_bot_in_flight_limit,
        )
    return LocalAdmissionController(limit=settings.effective_bot_in_flight_limit)


__all__ = ["create_dispatcher", "build_dispatcher"]
