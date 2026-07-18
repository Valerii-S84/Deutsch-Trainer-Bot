from __future__ import annotations

import json

import pytest

from app.runtime.webhook_ingress_handler import FastWebhookIngressHandler, TELEGRAM_SECRET_HEADER
from app.runtime.webhook_ingress_queue import WebhookEnqueueResult, WebhookIngressQueueError


@pytest.mark.asyncio
async def test_fast_webhook_ingress_valid_update_returns_quick_200_without_db_session(monkeypatch) -> None:
    queue = _QueueSpy(WebhookEnqueueResult(accepted=True, duplicate=False, update_id=101, stream_id="1-0"))
    handler = FastWebhookIngressHandler(queue=queue, secret_token="secret")

    monkeypatch.setattr("app.db.session.AsyncSessionLocal", _fail_db_session_factory)
    response = await handler.handle(_RequestStub({"update_id": 101}, secret="secret"))

    assert response.status == 200
    assert _payload(response) == {"ok": True, "status": "queued", "update_id": 101, "stream_id": "1-0"}
    assert queue.payloads == [{"update_id": 101}]


@pytest.mark.asyncio
async def test_fast_webhook_ingress_malformed_payload_returns_400_and_keeps_process_alive() -> None:
    handler = FastWebhookIngressHandler(queue=_QueueSpy(None), secret_token="secret")

    response = await handler.handle(_RequestStub(ValueError("bad json"), secret="secret"))

    assert response.status == 400
    assert _payload(response) == {"ok": False, "error": "invalid_json"}


@pytest.mark.asyncio
async def test_fast_webhook_ingress_duplicate_update_returns_duplicate_without_extra_event() -> None:
    queue = _QueueSpy(WebhookEnqueueResult(accepted=False, duplicate=True, update_id=101, stream_id=None))
    handler = FastWebhookIngressHandler(queue=queue, secret_token="secret")

    response = await handler.handle(_RequestStub({"update_id": 101}, secret="secret"))

    assert response.status == 200
    assert _payload(response)["status"] == "duplicate"
    assert _payload(response)["stream_id"] is None
    assert len(queue.payloads) == 1


@pytest.mark.asyncio
async def test_fast_webhook_ingress_redis_error_returns_503_not_silent_success() -> None:
    handler = FastWebhookIngressHandler(queue=_QueueSpy(WebhookIngressQueueError("redis down")), secret_token="secret")

    response = await handler.handle(_RequestStub({"update_id": 101}, secret="secret"))

    assert response.status == 503
    assert _payload(response) == {"ok": False, "error": "queue_unavailable"}


@pytest.mark.asyncio
async def test_fast_webhook_ingress_rejects_bad_secret_before_enqueue() -> None:
    queue = _QueueSpy(WebhookEnqueueResult(accepted=True, duplicate=False, update_id=101, stream_id="1-0"))
    handler = FastWebhookIngressHandler(queue=queue, secret_token="secret")

    response = await handler.handle(_RequestStub({"update_id": 101}, secret="wrong"))

    assert response.status == 401
    assert queue.payloads == []


class _RequestStub:
    def __init__(self, payload: object, *, secret: str) -> None:
        self.headers = {TELEGRAM_SECRET_HEADER: secret}
        self._payload = payload

    async def json(self) -> object:
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class _QueueSpy:
    def __init__(self, result: WebhookEnqueueResult | Exception | None) -> None:
        self._result = result
        self.payloads: list[dict[str, object]] = []

    async def enqueue_update(self, payload: dict[str, object]) -> WebhookEnqueueResult:
        self.payloads.append(payload)
        if isinstance(self._result, Exception):
            raise self._result
        assert self._result is not None
        return self._result


def _payload(response) -> dict[str, object]:
    return json.loads(response.text)


def _fail_db_session_factory():
    raise AssertionError("fast webhook ACK path must not open a DB session")
