"""Bot package for Telegram integration layers."""

from __future__ import annotations

from app.bot.dispatcher import create_dispatcher

__all__ = ["create_dispatcher"]
