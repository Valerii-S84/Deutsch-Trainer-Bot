from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app.config import Settings
from app.runtime import webhook_ingress_asgi
from app.runtime.webhook_ingress_asgi import TELEGRAM_SECRET_HEADER, WebhookIngressAsgiApp
from app.runtime.webhook_ingress_queue import WebhookEnqueueResult


@pytest.mark.asyncio
async def test_asgi_webhook_reuses_single_redis_client_across_requests(monkeypatch) -> None:
    redis_client = SimpleNamespace(ping=_AsyncCall(True))
    created_clients = []

    def create_redis_client(_settings):
        created_clients.append(redis_client)
        return redis_client

    monkeypatch.setattr(webhook_ingress_asgi, "create_redis_client", create_redis_client)
    monkeypatch.setattr(webhook_ingress_asgi, "warm_redis_client", _warm_redis_client)
    monkeypatch.setattr(webhook_ingress_asgi.WebhookIngressQueue, "warm", _queue_warm)
    monkeypatch.setattr(
        webhook_ingress_asgi.WebhookIngressQueue,
        "enqueue_update",
        _queue_enqueue_update,
    )
    app = WebhookIngressAsgiApp(
        Settings(
            telegram_webhook_secret="secret",
            telegram_webhook_path="/telegram/webhook",
            WEBHOOK_INGRESS_ENQUEUE_BATCH_SIZE=1,
            REDIS_WARMUP_CONNECTIONS=0,
        )
    )

    first = await _post(app, {"update_id": 101})
    second = await _post(app, {"update_id": 102})

    assert first["status"] == 200
    assert second["status"] == 200
    assert created_clients == [redis_client]


@pytest.mark.asyncio
async def test_asgi_webhook_rejects_malformed_payload_before_startup(monkeypatch) -> None:
    create_redis_client = _CallRecorder()
    monkeypatch.setattr(webhook_ingress_asgi, "create_redis_client", create_redis_client)
    app = WebhookIngressAsgiApp(
        Settings(
            telegram_webhook_secret="secret",
            telegram_webhook_path="/telegram/webhook",
        )
    )

    response = await _raw_post(app, b"{bad-json")

    assert response["status"] == 400
    assert create_redis_client.calls == 0


async def _post(app: WebhookIngressAsgiApp, payload: dict[str, object]) -> dict[str, object]:
    return await _raw_post(app, json.dumps(payload).encode("utf-8"))


async def _raw_post(app: WebhookIngressAsgiApp, body: bytes) -> dict[str, object]:
    sent: list[dict[str, object]] = []

    async def receive() -> dict[str, object]:
        return {"type": "http.request", "body": body, "more_body": False}

    async def send(message: dict[str, object]) -> None:
        sent.append(message)

    await app(
        {
            "type": "http",
            "method": "POST",
            "path": "/telegram/webhook",
            "headers": [(TELEGRAM_SECRET_HEADER, b"secret")],
        },
        receive,
        send,
    )
    start = sent[0]
    body_message = sent[1]
    return {
        "status": start["status"],
        "body": json.loads(body_message["body"].decode("utf-8")),
    }


async def _warm_redis_client(_redis_client, *, connection_count: int) -> dict[str, int]:
    return {"requested": connection_count, "succeeded": connection_count, "failed": 0}


async def _queue_warm(_queue) -> None:
    return None


async def _queue_enqueue_update(_queue, payload: dict[str, object]) -> WebhookEnqueueResult:
    return WebhookEnqueueResult(
        accepted=True,
        duplicate=False,
        update_id=int(payload["update_id"]),
        stream_id="1-0",
    )


class _AsyncCall:
    def __init__(self, result: object) -> None:
        self.result = result

    async def __call__(self) -> object:
        return self.result


class _CallRecorder:
    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, *args: object, **kwargs: object) -> object:
        del args, kwargs
        self.calls += 1
        raise AssertionError("malformed payload must not initialize Redis")
