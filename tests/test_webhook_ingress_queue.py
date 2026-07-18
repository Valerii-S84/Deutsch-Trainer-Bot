from __future__ import annotations

import json

import pytest
from redis.exceptions import RedisError

from app.runtime.webhook_ingress_queue import (
    InvalidWebhookUpdateError,
    WebhookEnqueueResult,
    WebhookIngressQueueError,
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


@pytest.mark.asyncio
async def test_enqueue_updates_reuses_loaded_batch_script_for_follow_up_batches() -> None:
    redis_client = _RedisBatchStub([[1, "1000-0"], [1, "1001-0"]])
    queue = _queue(redis_client)

    await queue.enqueue_updates([_update(101)])
    await queue.enqueue_updates([_update(102)])

    assert redis_client.script_load_calls == 1
    assert len(redis_client.evalsha_calls) == 2


@pytest.mark.asyncio
async def test_duplicate_batch_result_does_not_report_stream_id() -> None:
    redis_client = _RedisBatchStub([[0, ""], [0, ""]])
    queue = _queue(redis_client)

    results = await queue.enqueue_updates([_update(101), _update(101)])

    assert [result.duplicate for result in results if isinstance(result, WebhookEnqueueResult)] == [True, True]
    assert [result.stream_id for result in results if isinstance(result, WebhookEnqueueResult)] == [None, None]


@pytest.mark.asyncio
async def test_enqueue_update_raises_queue_error_when_redis_enqueue_fails() -> None:
    redis_client = _FailingRedisStub()
    queue = _queue(redis_client)

    with pytest.raises(WebhookIngressQueueError, match="webhook_ingress_enqueue_unavailable"):
        await queue.enqueue_update(_update(101))


@pytest.mark.asyncio
async def test_mark_processed_many_acks_batch_and_records_processing_metrics() -> None:
    redis_client = _RedisMetricsStub()
    queue = _queue(redis_client)

    await queue.mark_processed_many(
        [
            _message("1000-0", 101),
            _message("1001-0", 102),
        ],
        dispatch_durations_ms=[1.5, 2.5],
    )

    pipe = redis_client.pipeline_instance
    assert pipe.calls[0] == ("xack", "dtb:webhook_ingress:updates", "workers", ("1000-0", "1001-0"))
    assert pipe.calls[1] == ("xdel", "dtb:webhook_ingress:updates", ("1000-0", "1001-0"))
    assert ("incrby", "dtb:webhook_ingress:metrics:processed_total", 2) in pipe.calls
    assert ("lpush", "dtb:webhook_ingress:metrics:worker_dispatch_ms", "1.5") in pipe.calls
    assert ("lpush", "dtb:webhook_ingress:metrics:worker_dispatch_ms", "2.5") in pipe.calls


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


class _FailingRedisStub:
    async def script_load(self, _script: str) -> str:
        return "sha"

    async def evalsha(self, *args: object) -> object:
        del args
        raise RedisError("down")


class _RedisMetricsStub:
    def __init__(self) -> None:
        self.pipeline_instance = _PipelineSpy()

    async def time(self) -> tuple[int, int]:
        return 2, 0

    def pipeline(self):
        return self.pipeline_instance


class _PipelineSpy:
    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []

    def xack(self, stream_key: str, group_name: str, *message_ids: str) -> None:
        self.calls.append(("xack", stream_key, group_name, message_ids))

    def xdel(self, stream_key: str, *message_ids: str) -> None:
        self.calls.append(("xdel", stream_key, message_ids))

    def incrby(self, key: str, amount: int) -> None:
        self.calls.append(("incrby", key, amount))

    def lpush(self, key: str, value: str) -> None:
        self.calls.append(("lpush", key, value))

    def ltrim(self, key: str, start: int, end: int) -> None:
        self.calls.append(("ltrim", key, start, end))

    async def execute(self) -> list[object]:
        return []


def _queue(redis_client) -> WebhookIngressQueue:
    return WebhookIngressQueue(
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


def _update(update_id: int) -> dict[str, object]:
    return {"update_id": update_id, "message": {"text": "/start"}}


def _message(message_id: str, update_id: int):
    from app.runtime.webhook_ingress_queue import WebhookStreamMessage

    return WebhookStreamMessage(
        message_id=message_id,
        update_id=update_id,
        payload=json.loads(json.dumps(_update(update_id))),
        enqueued_at_ms=1000,
        attempt=0,
    )
