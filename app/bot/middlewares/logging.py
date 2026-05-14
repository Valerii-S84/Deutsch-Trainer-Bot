"""Logging middleware for incoming updates."""

from __future__ import annotations

import logging
from typing import Any

from aiogram import BaseMiddleware

logger = logging.getLogger(__name__)


class LoggingMiddleware(BaseMiddleware):
    """Log update metadata without leaking payload details or secrets."""

    async def __call__(self, handler: Any, event: Any, data: dict[str, Any]) -> Any:
        update_obj = data.get("event_update")
        update_id = getattr(update_obj, "update_id", None)
        user = getattr(event, "from_user", None)
        user_id = getattr(user, "id", None)
        chat = getattr(event, "chat", None)
        chat_id = getattr(chat, "id", None)
        event_type = event.__class__.__name__ if event else None

        logger.info(
            "incoming update: id=%s type=%s user_id=%s chat_id=%s",
            update_id,
            event_type,
            user_id,
            chat_id,
        )
        return await handler(event, data)
