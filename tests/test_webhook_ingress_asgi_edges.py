from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

from app.config import Settings
from app.runtime import webhook_ingress_asgi
from app.runtime.webhook_ingress_asgi import (
    MAX_WEBHOOK_BODY_BYTES,
    TELEGRAM_SECRET_HEADER,
    WebhookIngressAsgiApp,
    _WebhookEnqueueBatcher,
    _extract_update_id,
)
from app.runtime.webhook_ingress_queue import InvalidWebhookUpdateError, WebhookEnqueueResult


@pytest.mark.asyncio
async def test_asgi_health_not_found_and_unauthorized_paths_do_not_start_redis(monkeypatch) -> None:
    create_redis_client = _CallRecorder()
    monkeypatch.setattr(webhook_ingress_asgi, "create_redis_client", create_redis_client)
    app = _app()

    health = await _request(app, method="GET", path="/health")
    missing = await _request(app, method="GET", path="/missing")
    unauthorized = await _request(app, headers=[(TELEGRAM_SECRET_HEADER, b"wrong")])
    unsupported = await _scope_request(app, {"type": "websocket"})

    assert health["status"] == 200
    assert missing["status"] == 404
    assert unauthorized["status"] == 401
    assert unsupported["status"] == 404
    assert create_redis_client.calls == 0


@pytest.mark.asyncio
async def test_asgi_rejects_non_object_and_oversized_payload_before_startup(monkeypatch) -> None:
    create_redis_client = _CallRecorder()
    monkeypatch.setattr(webhook_ingress_asgi, "create_redis_client", create_redis_client)
    app = _app()

    non_object = await _request(app, body=b"[]")
    oversized = await _request(app, body=b" " * (MAX_WEBHOOK_BODY_BYTES + 1))

    assert non_object["status"] == 400
    assert non_object["body"]["error"] == "invalid_update"
    assert oversized["status"] == 400
    assert oversized["body"]["error"] == "invalid_json"
    assert create_redis_client.calls == 0


@pytest.mark.asyncio
async def test_asgi_ready_reports_unavailable_when_ping_fails(monkeypatch) -> None:
    redis_client = SimpleNamespace(ping=_AsyncRaises(RuntimeError("down")))
    monkeypatch.setattr(webhook_ingress_asgi, "create_redis_client", lambda _settings: redis_client)
    monkeypatch.setattr(webhook_ingress_asgi.WebhookIngressQueue, "warm", _async_noop)
    app = _app()

    response = await _request(app, method="GET", path="/ready")

    assert response["status"] == 503
    assert response["body"] == {"status": "unavailable"}


@pytest.mark.asyncio
async def test_asgi_lifespan_startup_and_shutdown_manage_resources(monkeypatch) -> None:
    redis_client = object()
    close_calls: list[object] = []
    monkeypatch.setattr(webhook_ingress_asgi, "create_redis_client", lambda _settings: redis_client)
    monkeypatch.setattr(webhook_ingress_asgi, "warm_redis_client", _warm_redis_client)
    monkeypatch.setattr(webhook_ingress_asgi.WebhookIngressQueue, "warm", _async_noop)

    async def close_redis_client(client):
        close_calls.append(client)

    monkeypatch.setattr(webhook_ingress_asgi, "close_redis_client", close_redis_client)
    app = _app(batch_size=1, warmup=2)

    sent = await _lifespan(app, [{"type": "lifespan.startup"}, {"type": "lifespan.shutdown"}])

    assert [message["type"] for message in sent] == [
        "lifespan.startup.complete",
        "lifespan.shutdown.complete",
    ]
    assert close_calls == [redis_client]


@pytest.mark.asyncio
async def test_asgi_ack_before_redis_returns_after_validating_update_id(monkeypatch) -> None:
    queue = _QueueSpy()
    app = _app(ack_before_redis=True)
    app._queue = queue

    response = await _request(app, payload={"update_id": 555})

    await asyncio.sleep(0)
    assert response["status"] == 200
    assert response["body"]["status"] == "queued"
    assert queue.updates == [{"update_id": 555}]

    with pytest.raises(InvalidWebhookUpdateError):
        _extract_update_id({"update_id": True})


@pytest.mark.asyncio
async def test_webhook_batcher_propagates_errors_for_waiting_calls_and_logs_buffered_failures() -> None:
    queue = _BatchQueueSpy([RuntimeError("redis down")])
    batcher = _WebhookEnqueueBatcher(queue, batch_size=2, flush_interval_ms=1)

    waiting = asyncio.create_task(batcher.enqueue({"update_id": 1}))
    buffered = await batcher.enqueue_buffered({"update_id": 2})
    failed_future = waiting.get_loop().create_future()
    await batcher._flush(
        [
            webhook_ingress_asgi._PendingWebhookUpdate({"update_id": 1}, failed_future),
            webhook_ingress_asgi._PendingWebhookUpdate({"update_id": 2}, None),
        ]
    )
    waiting.cancel()

    assert buffered.update_id == 2
    with pytest.raises(RuntimeError, match="redis down"):
        failed_future.result()


@pytest.mark.asyncio
async def test_webhook_batcher_sets_results_from_batch_queue() -> None:
    queue = _BatchQueueSpy(
        [
            WebhookEnqueueResult(True, False, 1, "1-0"),
            InvalidWebhookUpdateError("bad"),
        ]
    )
    batcher = _WebhookEnqueueBatcher(queue, batch_size=2, flush_interval_ms=1)
    loop = asyncio.get_running_loop()
    ok_future = loop.create_future()
    bad_future = loop.create_future()

    await batcher._flush(
        [
            webhook_ingress_asgi._PendingWebhookUpdate({"update_id": 1}, ok_future),
            webhook_ingress_asgi._PendingWebhookUpdate({"bad": True}, bad_future),
        ]
    )

    assert ok_future.result().stream_id == "1-0"
    with pytest.raises(InvalidWebhookUpdateError):
        bad_future.result()


class _QueueSpy:
    def __init__(self) -> None:
        self.updates: list[dict[str, object]] = []

    async def enqueue_update(self, payload):
        self.updates.append(payload)
        return WebhookEnqueueResult(True, False, int(payload["update_id"]), "1-0")


class _BatchQueueSpy:
    def __init__(self, results_or_error) -> None:
        self._results_or_error = results_or_error

    async def enqueue_updates(self, payloads):
        if isinstance(self._results_or_error, Exception):
            raise self._results_or_error
        if self._results_or_error and isinstance(self._results_or_error[0], Exception):
            raise self._results_or_error[0]
        return self._results_or_error


class _AsyncRaises:
    def __init__(self, exc: Exception) -> None:
        self._exc = exc

    async def __call__(self):
        raise self._exc


class _CallRecorder:
    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, *_args, **_kwargs):
        self.calls += 1
        raise AssertionError("Redis must not be initialized")


async def _async_noop(*_args, **_kwargs) -> None:
    return None


async def _warm_redis_client(_redis_client, *, connection_count: int):
    return {"requested": connection_count, "succeeded": connection_count, "failed": 0}


def _app(*, batch_size: int = 1, warmup: int = 0, ack_before_redis: bool = False) -> WebhookIngressAsgiApp:
    return WebhookIngressAsgiApp(
        Settings(
            telegram_webhook_secret="secret",
            telegram_webhook_path="/telegram/webhook",
            WEBHOOK_INGRESS_ENQUEUE_BATCH_SIZE=batch_size,
            WEBHOOK_INGRESS_ACK_BEFORE_REDIS=ack_before_redis,
            REDIS_WARMUP_CONNECTIONS=warmup,
            REDIS_MAX_CONNECTIONS=5,
        )
    )


async def _request(
    app: WebhookIngressAsgiApp,
    *,
    method: str = "POST",
    path: str = "/telegram/webhook",
    headers: list[tuple[bytes, bytes]] | None = None,
    payload: dict[str, object] | None = None,
    body: bytes | None = None,
) -> dict[str, object]:
    raw_body = body if body is not None else json.dumps(payload or {"update_id": 101}).encode()
    return await _scope_request(
        app,
        {
            "type": "http",
            "method": method,
            "path": path,
            "headers": headers or [(TELEGRAM_SECRET_HEADER, b"secret")],
        },
        body=raw_body,
    )


async def _scope_request(app: WebhookIngressAsgiApp, scope: dict[str, object], *, body: bytes = b"") -> dict[str, object]:
    sent: list[dict[str, object]] = []

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    async def send(message):
        sent.append(message)

    await app(scope, receive, send)
    start = sent[0]
    response_body = sent[1].get("body", b"{}") if len(sent) > 1 else b"{}"
    return {"status": start["status"], "body": json.loads(response_body.decode())}


async def _lifespan(app: WebhookIngressAsgiApp, messages: list[dict[str, object]]) -> list[dict[str, object]]:
    sent: list[dict[str, object]] = []
    pending = list(messages)

    async def receive():
        return pending.pop(0)

    async def send(message):
        sent.append(message)

    await app({"type": "lifespan"}, receive, send)
    return sent
