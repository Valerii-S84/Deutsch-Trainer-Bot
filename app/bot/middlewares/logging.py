"""Logging middleware for incoming updates."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class LoggingMiddleware:
    """Log update metadata without leaking payload details or secrets."""

    async def __call__(self, handler: Any, event: Any, data: dict[str, Any]) -> Any:
        update_obj = data.get("event_update")
        update_id = getattr(update_obj, "update_id", None)
        event_type, event_payload = self._event_payload(update_obj, event)
        user = getattr(event_payload, "from_user", None)
        user_id = getattr(user, "id", None)
        chat = self._chat_from_payload(event_payload)
        chat_id = getattr(chat, "id", None)
        callback_route = self._callback_route(event_payload)

        logger.info(
            "incoming update: id=%s type=%s user_id=%s chat_id=%s callback_route=%s",
            update_id,
            event_type,
            user_id,
            chat_id,
            callback_route,
        )
        return await handler(event, data)

    @staticmethod
    def _event_payload(update_obj: Any, event: Any) -> tuple[str | None, Any]:
        if update_obj:
            for event_type in (
                "message",
                "callback_query",
                "edited_message",
                "pre_checkout_query",
                "successful_payment",
            ):
                payload = getattr(update_obj, event_type, None)
                if payload is not None:
                    return event_type, payload
        return event.__class__.__name__ if event else None, event

    @staticmethod
    def _chat_from_payload(event_payload: Any) -> Any:
        chat = getattr(event_payload, "chat", None)
        if chat is not None:
            return chat
        message = getattr(event_payload, "message", None)
        return getattr(message, "chat", None)

    @classmethod
    def _callback_route(cls, event_payload: Any) -> str | None:
        raw_data = getattr(event_payload, "data", None)
        if not isinstance(raw_data, str) or not raw_data.strip():
            return None

        parts = raw_data.split(":")
        prefix = parts[0]
        if prefix in {"bot", "menu", "review"} and len(parts) >= 2:
            return f"{prefix}:{parts[1]}"
        if prefix in {"payment", "train"} and len(parts) >= 2:
            return f"{prefix}:{parts[1]}"
        if prefix in {"level", "theme"}:
            return prefix
        return prefix or "unknown"
