from __future__ import annotations

import pytest

from app.runtime.webhook_ingress_queue import (
    InvalidWebhookUpdateError,
    WebhookEnqueueResult,
    WebhookIngressQueue,
    WebhookIngressQueueSettings,
)


@pytest.mark.asyncio
async def test_enqueue_updates_uses_one_batch_script_and_preserves_result_order() -> None:
    redis_client = _RedisBatchStub(
        [
            [1, "1000-0"],
            [0, ""],
        ],
    )
    queue = WebhookIngressQueue(
        redis_client,
        WebhookIngressQueueSettings(
            stream_key="dtb:webhook_ingress:updates",
            group_name="workers",
            dead_letter_key="dtb:webhook_ingress:dead",
            dedupe_key_prefix="dtb:webhook_ingress:dedupe",
            metrics_key_prefix="dtb:webhook_ingress:metrics",
            dedupe_ttl_seconds=300,
            processing_lag_sample_size=100,
        ),
    )

    results = await queue.enqueue_updates(
        [
            {"update_id": 101, "message": {"text": "/start"}},
            {"message": {"text": "invalid"}},
            {"update_id": 102, "message": {"text": "/help"}},
        ],
    )

    assert redis_client.script_load_calls == 1
    assert len(redis_client.evalsha_calls) == 1
    assert redis_client.evalsha_calls[0][1] == 1
    assert redis_client.evalsha_calls[0][2] == "dtb:webhook_ingress:updates"
    assert redis_client.evalsha_calls[0][3:5] == (300, "0")
    assert redis_client.evalsha_calls[0][5] == "dtb:webhook_ingress:dedupe:101"
    assert redis_client.evalsha_calls[0][8] == "dtb:webhook_ingress:dedupe:102"

    first, second, third = results
    assert isinstance(first, WebhookEnqueueResult)
    assert first.accepted is True
    assert first.duplicate is False
    assert first.update_id == 101
    assert first.stream_id == "1000-0"
    assert isinstance(second, InvalidWebhookUpdateError)
    assert isinstance(third, WebhookEnqueueResult)
    assert third.accepted is False
    assert third.duplicate is True
    assert third.update_id == 102
    assert third.stream_id is None


class _RedisBatchStub:
    def __init__(self, evalsha_result: list[list[object]]) -> None:
        self._evalsha_result = evalsha_result
        self.script_load_calls = 0
        self.evalsha_calls: list[tuple[object, ...]] = []

    async def script_load(self, _script: str) -> str:
        self.script_load_calls += 1
        return "sha-batch"

    async def evalsha(self, *args: object) -> list[list[object]]:
        self.evalsha_calls.append(args)
        return self._evalsha_result
