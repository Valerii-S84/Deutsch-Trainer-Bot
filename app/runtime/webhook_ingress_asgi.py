from __future__ import annotations

import asyncio
from dataclasses import dataclass
import json
import logging
from typing import Any

from redis.asyncio import Redis

from app.config import Settings, get_settings
from app.runtime.redis import close_redis_client, create_redis_client, warm_redis_client
from app.runtime.webhook_ingress_queue import (
    InvalidWebhookUpdateError,
    WebhookEnqueueResult,
    WebhookIngressQueue,
    WebhookIngressQueueError,
    WebhookIngressQueueSettings,
)

logger = logging.getLogger(__name__)

TELEGRAM_SECRET_HEADER = b"x-telegram-bot-api-secret-token"
MAX_WEBHOOK_BODY_BYTES = 2 * 1024 * 1024


class WebhookIngressAsgiApp:
    """Minimal ASGI app for Redis-backed Telegram webhook ACKs."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._redis_client: Redis | None = None
        self._queue: WebhookIngressQueue | None = None
        self._batcher: _WebhookEnqueueBatcher | None = None
        self._startup_lock = asyncio.Lock()

    async def __call__(self, scope: dict[str, Any], receive, send) -> None:
        scope_type = scope.get("type")
        if scope_type == "lifespan":
            await self._handle_lifespan(receive, send)
            return
        if scope_type != "http":
            await _send_json(send, 404, {"ok": False, "error": "not_found"})
            return
        await self._handle_http(scope, receive, send)

    async def _handle_lifespan(self, receive, send) -> None:
        while True:
            message = await receive()
            message_type = message.get("type")
            if message_type == "lifespan.startup":
                await self._lifespan_startup(send)
                continue
            elif message_type == "lifespan.shutdown":
                await self._lifespan_shutdown(send)
                return

    async def _lifespan_startup(self, send) -> None:
        try:
            await self._ensure_started()
        except Exception as exc:
            await send({"type": "lifespan.startup.failed", "message": str(exc)})
            return
        await send({"type": "lifespan.startup.complete"})

    async def _lifespan_shutdown(self, send) -> None:
        if self._batcher is not None:
            await self._batcher.close()
        await close_redis_client(self._redis_client)
        await send({"type": "lifespan.shutdown.complete"})

    async def _handle_http(self, scope: dict[str, Any], receive, send) -> None:
        method = str(scope.get("method", "")).upper()
        path = str(scope.get("path", ""))
        if method == "GET" and path == "/health":
            await _send_json(send, 200, {"status": "ok"})
            return
        if method == "GET" and path == "/ready":
            await self._handle_ready(send)
            return
        if method != "POST" or path != self._settings.telegram_webhook_path:
            await _send_json(send, 404, {"ok": False, "error": "not_found"})
            return
        await self._handle_webhook(scope, receive, send)

    async def _handle_ready(self, send) -> None:
        try:
            await self._ensure_started()
            redis_client = self._redis_client
            if redis_client is None:
                raise RuntimeError("asgi webhook ingress redis client is not initialized")
            await redis_client.ping()
        except Exception as exc:
            logger.warning("asgi webhook ingress readiness failed: %s", exc.__class__.__name__)
            await _send_json(send, 503, {"status": "unavailable"})
            return
        await _send_json(send, 200, {"status": "ok"})

    async def _handle_webhook(self, scope: dict[str, Any], receive, send) -> None:
        secret = self._settings.telegram_webhook_secret
        expected_secret = secret.get_secret_value() if secret else ""
        if _header(scope, TELEGRAM_SECRET_HEADER) != expected_secret:
            await _send_json(send, 401, {"ok": False, "error": "unauthorized"})
            return

        try:
            payload = json.loads((await _read_body(receive)).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
            await _send_json(send, 400, {"ok": False, "error": "invalid_json"})
            return
        if not isinstance(payload, dict):
            await _send_json(send, 400, {"ok": False, "error": "invalid_update"})
            return

        try:
            await self._ensure_started()
            result = await self._enqueue_update(payload)
        except InvalidWebhookUpdateError:
            await _send_json(send, 400, {"ok": False, "error": "invalid_update"})
            return
        except WebhookIngressQueueError as exc:
            logger.warning("asgi webhook ingress queue unavailable: %s", exc)
            await _send_json(send, 503, {"ok": False, "error": "queue_unavailable"})
            return

        await _send_json(
            send,
            200,
            {
                "ok": True,
                "status": "duplicate" if result.duplicate else "queued",
                "update_id": result.update_id,
            },
        )

    async def _ensure_started(self) -> None:
        if self._queue is not None:
            return
        async with self._startup_lock:
            if self._queue is not None:
                return
            redis_client = create_redis_client(self._settings)
            if self._settings.redis_warmup_connections > 0:
                await warm_redis_client(
                    redis_client,
                    connection_count=min(
                        self._settings.redis_warmup_connections,
                        self._settings.redis_max_connections,
                    ),
                )
            self._redis_client = redis_client
            self._queue = WebhookIngressQueue(
                redis_client,
                WebhookIngressQueueSettings(
                    stream_key=self._settings.webhook_ingress_stream_key,
                    group_name=self._settings.webhook_ingress_group_name,
                    dead_letter_key=self._settings.webhook_ingress_dead_letter_key,
                    dedupe_key_prefix=self._settings.webhook_ingress_dedupe_key_prefix,
                    metrics_key_prefix=self._settings.webhook_ingress_metrics_key_prefix,
                    dedupe_ttl_seconds=self._settings.telegram_duplicate_update_ttl_seconds,
                    processing_lag_sample_size=self._settings.webhook_ingress_processing_lag_sample_size,
                ),
            )
            await self._queue.warm()
            if self._settings.webhook_ingress_enqueue_batch_size > 1:
                self._batcher = _WebhookEnqueueBatcher(
                    self._queue,
                    batch_size=self._settings.webhook_ingress_enqueue_batch_size,
                    flush_interval_ms=self._settings.webhook_ingress_enqueue_flush_interval_ms,
                )
                self._batcher.start()

    async def _enqueue_update(self, payload: dict[str, Any]) -> WebhookEnqueueResult:
        if self._batcher is not None:
            if self._settings.webhook_ingress_ack_before_redis:
                return await self._batcher.enqueue_buffered(payload)
            return await self._batcher.enqueue(payload)
        queue = self._queue
        if queue is None:
            raise WebhookIngressQueueError("webhook_ingress_queue_uninitialized")
        if self._settings.webhook_ingress_ack_before_redis:
            update_id = _extract_update_id(payload)
            asyncio.create_task(queue.enqueue_update(payload))
            return WebhookEnqueueResult(accepted=True, duplicate=False, update_id=update_id, stream_id=None)
        return await queue.enqueue_update(payload)


@dataclass(frozen=True, slots=True)
class _PendingWebhookUpdate:
    payload: dict[str, Any]
    future: asyncio.Future[WebhookEnqueueResult] | None


class _WebhookEnqueueBatcher:
    def __init__(
        self,
        queue: WebhookIngressQueue,
        *,
        batch_size: int,
        flush_interval_ms: int,
    ) -> None:
        self._queue = queue
        self._batch_size = max(1, batch_size)
        self._flush_interval_seconds = max(0.001, flush_interval_ms / 1000)
        self._pending: asyncio.Queue[_PendingWebhookUpdate] = asyncio.Queue()
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run())

    async def close(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            return

    async def enqueue(self, payload: dict[str, Any]) -> WebhookEnqueueResult:
        loop = asyncio.get_running_loop()
        future: asyncio.Future[WebhookEnqueueResult] = loop.create_future()
        await self._pending.put(_PendingWebhookUpdate(payload=payload, future=future))
        return await future

    async def enqueue_buffered(self, payload: dict[str, Any]) -> WebhookEnqueueResult:
        update_id = _extract_update_id(payload)
        await self._pending.put(_PendingWebhookUpdate(payload=payload, future=None))
        return WebhookEnqueueResult(accepted=True, duplicate=False, update_id=update_id, stream_id=None)

    async def _run(self) -> None:
        while True:
            first = await self._pending.get()
            batch = [first]
            deadline = asyncio.get_running_loop().time() + self._flush_interval_seconds
            while len(batch) < self._batch_size:
                timeout = deadline - asyncio.get_running_loop().time()
                if timeout <= 0:
                    break
                try:
                    batch.append(await asyncio.wait_for(self._pending.get(), timeout=timeout))
                except TimeoutError:
                    break
            await self._flush(batch)

    async def _flush(self, batch: list[_PendingWebhookUpdate]) -> None:
        try:
            results = await self._queue.enqueue_updates([item.payload for item in batch])
        except Exception as exc:
            buffered_count = 0
            for item in batch:
                if item.future is None:
                    buffered_count += 1
                    continue
                if not item.future.done():
                    item.future.set_exception(exc)
            if buffered_count:
                logger.warning(
                    "asgi webhook ingress buffered Redis flush failed for %s update(s): %s",
                    buffered_count,
                    exc.__class__.__name__,
                )
            return

        for item, result in zip(batch, results):
            if item.future is None or item.future.done():
                continue
            if isinstance(result, Exception):
                item.future.set_exception(result)
            else:
                item.future.set_result(result)


def create_app() -> WebhookIngressAsgiApp:
    return WebhookIngressAsgiApp()


def _extract_update_id(payload: dict[str, Any]) -> int:
    update_id = payload.get("update_id")
    if isinstance(update_id, bool) or not isinstance(update_id, int):
        raise InvalidWebhookUpdateError("telegram update_id must be an integer")
    return update_id


async def _read_body(receive) -> bytes:
    chunks: list[bytes] = []
    total = 0
    more_body = True
    while more_body:
        message = await receive()
        chunk = message.get("body", b"")
        if chunk:
            total += len(chunk)
            if total > MAX_WEBHOOK_BODY_BYTES:
                raise ValueError("webhook body too large")
            chunks.append(chunk)
        more_body = bool(message.get("more_body", False))
    return b"".join(chunks)


def _header(scope: dict[str, Any], name: bytes) -> str:
    for key, value in scope.get("headers", []):
        if key.lower() == name:
            return value.decode("utf-8", errors="replace")
    return ""


async def _send_json(send, status: int, payload: dict[str, Any]) -> None:
    body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode("ascii")),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})
