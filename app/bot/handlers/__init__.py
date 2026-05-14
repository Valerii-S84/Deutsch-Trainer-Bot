from __future__ import annotations

"""Handler package exports."""

from app.bot.handlers.fallback import router as fallback_router
from app.bot.handlers.level import router as level_router
from app.bot.handlers.menu import router as menu_router
from app.bot.handlers.profile import router as profile_router
from app.bot.handlers.review import router as review_router
from app.bot.handlers.training import router as training_router
from app.bot.handlers.start import router as start_router
from app.bot.handlers.subscription import router as subscription_router
from app.bot.handlers.theme import router as theme_router

__all__ = [
    "fallback_router",
    "level_router",
    "menu_router",
    "review_router",
    "training_router",
    "profile_router",
    "start_router",
    "subscription_router",
    "theme_router",
]
