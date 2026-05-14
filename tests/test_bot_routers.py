from __future__ import annotations

from app.bot.dispatcher import create_dispatcher
from app.bot.routers import build_root_router
from app.bot.middlewares.logging import LoggingMiddleware


def test_root_router_contains_all_feature_routers() -> None:
    router = build_root_router()
    names = {sub.name for sub in router.sub_routers}
    assert names == {"start", "menu", "level", "theme", "training", "profile", "subscription", "fallback"}


def test_dispatcher_includes_root_router() -> None:
    dispatcher = create_dispatcher()
    names = {sub.name for sub in dispatcher.sub_routers}
    assert "bot" in names


def test_dispatcher_has_logging_middleware() -> None:
    dispatcher = create_dispatcher()
    middlewares = dispatcher.update.__dict__["middleware"]._middlewares
    assert any(isinstance(item, LoggingMiddleware) for item in middlewares)
