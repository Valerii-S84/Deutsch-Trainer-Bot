"""Router graph composition for bot handlers."""

from __future__ import annotations

from copy import deepcopy

from aiogram import Router

from app.bot.handlers import fallback, level, menu, profile, start, subscription, theme, training


def _clone_router(router: Router) -> Router:
    """Clone routers to keep build methods re-entrant in tests and runtime usage."""
    return deepcopy(router)


def build_root_router() -> Router:
    """Build unified bot router with all entrypoints."""
    router = Router(name="bot")
    router.include_router(_clone_router(start.router))
    router.include_router(_clone_router(menu.router))
    router.include_router(_clone_router(level.router))
    router.include_router(_clone_router(theme.router))
    router.include_router(_clone_router(training.router))
    router.include_router(_clone_router(profile.router))
    router.include_router(_clone_router(subscription.router))
    router.include_router(_clone_router(fallback.router))
    return router


def build_dispatcher_router() -> Router:
    """Backward-compatible alias for code that expects a single builder."""
    return build_root_router()
