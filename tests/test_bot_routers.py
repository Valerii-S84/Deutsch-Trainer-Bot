from __future__ import annotations

from types import SimpleNamespace

from app.bot.dispatcher import create_dispatcher
from app.bot.routers import build_root_router
from app.bot.middlewares.backpressure import BackpressureMiddleware
from app.bot.middlewares.logging import LoggingMiddleware
from app.bot.middlewares.security import SecurityMiddleware
from app.config import Settings


def test_root_router_contains_all_feature_routers() -> None:
    router = build_root_router()
    names = {sub.name for sub in router.sub_routers}
    assert names == {
        "admin",
        "start",
        "menu",
        "level",
        "theme",
        "review",
        "training",
        "profile",
        "subscription",
        "payments",
        "fallback",
    }


def test_dispatcher_includes_root_router() -> None:
    dispatcher = create_dispatcher()
    names = {sub.name for sub in dispatcher.sub_routers}
    assert "bot" in names


def test_dispatcher_has_logging_middleware() -> None:
    dispatcher = create_dispatcher()
    middlewares = dispatcher.update.__dict__["middleware"]._middlewares
    assert any(isinstance(item, LoggingMiddleware) for item in middlewares)


def test_dispatcher_has_security_middleware() -> None:
    dispatcher = create_dispatcher()
    middlewares = dispatcher.update.__dict__["middleware"]._middlewares
    assert any(isinstance(item, SecurityMiddleware) for item in middlewares)


def test_dispatcher_has_backpressure_middleware() -> None:
    dispatcher = create_dispatcher()
    middlewares = dispatcher.update.__dict__["middleware"]._middlewares
    assert any(isinstance(item, BackpressureMiddleware) for item in middlewares)


def test_dispatcher_uses_effective_backpressure_limit_for_pgbouncer_backend() -> None:
    dispatcher = create_dispatcher(
        Settings(
            DB_CONNECTION_BACKEND="pgbouncer_transaction",
            DB_PGBOUNCER_MAX_CLIENT_CONN=200,
            DB_PGBOUNCER_CLIENT_HEADROOM=32,
        )
    )
    middlewares = dispatcher.update.__dict__["middleware"]._middlewares
    middleware = next(item for item in middlewares if isinstance(item, BackpressureMiddleware))

    assert middleware.limit == 168
    assert middleware.admission_limit == 168
    assert middleware.uses_shared_admission is False


def test_dispatcher_uses_shared_backpressure_when_redis_client_is_available() -> None:
    dispatcher = create_dispatcher(
        Settings(
            app_env="production",
            SECURITY_STATE_BACKEND="redis",
            DB_CONNECTION_BACKEND="pgbouncer_transaction",
            DB_PGBOUNCER_MAX_CLIENT_CONN=200,
            DB_PGBOUNCER_CLIENT_HEADROOM=32,
            DB_PGBOUNCER_REUSE_APP_CONNECTIONS=False,
            DB_APP_REPLICA_COUNT=4,
        ),
        redis_client=SimpleNamespace(),
    )
    middlewares = dispatcher.update.__dict__["middleware"]._middlewares
    middleware = next(item for item in middlewares if isinstance(item, BackpressureMiddleware))

    assert middleware.limit == 42
    assert middleware.admission_limit == 168
    assert middleware.uses_shared_admission is True
