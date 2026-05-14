"""Dispatcher factory for aiogram entrypoint."""

from __future__ import annotations

from aiogram import Dispatcher

from app.bot.middlewares import LoggingMiddleware
from app.bot.routers import build_root_router


def create_dispatcher() -> Dispatcher:
    """Create aiogram dispatcher with middleware and full router graph."""
    dispatcher = Dispatcher()
    dispatcher.include_router(build_root_router())
    dispatcher.update.middleware(LoggingMiddleware())
    return dispatcher


def build_dispatcher() -> Dispatcher:
    """Backward-compatible builder name used by existing runtime entrypoints/tests."""
    return create_dispatcher()


__all__ = ["create_dispatcher", "build_dispatcher"]
