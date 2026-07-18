from __future__ import annotations

import logging

from aiohttp import web

from app.runtime.webhook_ingress_queue import (
    InvalidWebhookUpdateError,
    WebhookIngressQueue,
    WebhookIngressQueueError,
)

logger = logging.getLogger(__name__)

TELEGRAM_SECRET_HEADER = "X-Telegram-Bot-Api-Secret-Token"  # nosec B105 - header name, not a secret value.


class FastWebhookIngressHandler:
    """Validate, deduplicate and enqueue Telegram updates without DB work."""

    def __init__(
        self,
        *,
        queue: WebhookIngressQueue,
        secret_token: str,
    ) -> None:
        self._queue = queue
        self._secret_token = secret_token

    def register(self, app: web.Application, *, path: str) -> None:
        app.router.add_post(path, self.handle)

    async def handle(self, request: web.Request) -> web.Response:
        if request.headers.get(TELEGRAM_SECRET_HEADER, "") != self._secret_token:
            return web.json_response({"ok": False, "error": "unauthorized"}, status=401)

        try:
            payload = await request.json()
        except Exception:
            return web.json_response({"ok": False, "error": "invalid_json"}, status=400)
        if not isinstance(payload, dict):
            return web.json_response({"ok": False, "error": "invalid_update"}, status=400)

        try:
            result = await self._queue.enqueue_update(payload)
        except InvalidWebhookUpdateError:
            return web.json_response({"ok": False, "error": "invalid_update"}, status=400)
        except WebhookIngressQueueError as exc:
            logger.warning("webhook ingress queue unavailable: %s", exc)
            return web.json_response({"ok": False, "error": "queue_unavailable"}, status=503)

        return web.json_response(
            {
                "ok": True,
                "status": "duplicate" if result.duplicate else "queued",
                "update_id": result.update_id,
                "stream_id": result.stream_id,
            },
        )
