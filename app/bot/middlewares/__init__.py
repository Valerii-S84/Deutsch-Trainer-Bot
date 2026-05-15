"""Middlewares for bot updates."""

from __future__ import annotations

from app.bot.middlewares.logging import LoggingMiddleware
from app.bot.middlewares.security import SecurityMiddleware

__all__ = ["LoggingMiddleware", "SecurityMiddleware"]
