"""Dispatcher factory for aiogram entrypoint."""

from __future__ import annotations

from aiogram import Dispatcher

from app.bot.middlewares import LoggingMiddleware, SecurityMiddleware
from app.bot.routers import build_root_router
from app.config import Settings, get_settings
from app.security.rate_limits import DuplicateUpdateGuard


def create_dispatcher(settings: Settings | None = None) -> Dispatcher:
    """Create aiogram dispatcher with middleware and full router graph."""
    settings = settings or get_settings()
    dispatcher = Dispatcher()
    dispatcher.include_router(build_root_router())
    dispatcher.update.middleware(
        SecurityMiddleware(
            duplicate_guard=DuplicateUpdateGuard(ttl_seconds=settings.telegram_duplicate_update_ttl_seconds),
            rate_limit_enabled=settings.security_rate_limit_enabled,
        ),
    )
    dispatcher.update.middleware(LoggingMiddleware())
    return dispatcher


def build_dispatcher() -> Dispatcher:
    """Backward-compatible builder name used by existing runtime entrypoints/tests."""
    return create_dispatcher()


__all__ = ["create_dispatcher", "build_dispatcher"]
