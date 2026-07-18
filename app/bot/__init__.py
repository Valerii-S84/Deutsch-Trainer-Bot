"""Bot package for Telegram integration layers."""

from __future__ import annotations

from typing import Any


def create_dispatcher(*args: Any, **kwargs: Any):
    """Create dispatcher lazily to avoid aiogram import during constants-only imports."""

    from app.bot.dispatcher import create_dispatcher as _create_dispatcher

    return _create_dispatcher(*args, **kwargs)

__all__ = ["create_dispatcher"]
