from __future__ import annotations

import json

import pytest
from redis.exceptions import NoScriptError, RedisError

from app.runtime.webhook_ingress_queue import (
    WebhookIngressQueue,
    WebhookIngressQueueError,
    WebhookIngressQueueSettings,
    WebhookStreamMessage,
    _decode_payload,
    _parse_enqueue_result,
    _parse_stream_batches,
    _parse_xautoclaim_result,
)


@pytest.mark.asyncio
async def test_webhook_queue_ensure_group_ignores_existing_group_and_wraps_other_errors() -> None:
    await _queue(_GroupRedisStub(RedisError("BUSYGROUP already exists"))).ensure_group()

    with pytest.raises(WebhookIngressQueueError, match="webhook_ingress_group_unavailable"):
        await _queue(_GroupRedisStub(RedisError("down"))).ensure_group()


@pytest.mark.asyncio
async def test_webhook_queue_read_and_claim_parse_messages_and_clamp_args() -> None:
    redis_client = _ReadRedisStub()
    queue = _queue(redis_client)

    messages = await queue.read_batch(consumer_name="worker-1", count=0, block_ms=0)
    claimed = await queue.claim_stale(consumer_name="worker-1", min_idle_ms=0, count=0)

    assert redis_client.xreadgroup_calls == [
        ("workers", "worker-1", {"dtb:webhook_ingress:updates": ">"}, 1, 1)
    ]
    assert messages[0].update_id == 101
    assert messages[0].payload["message"]["text"] == "/start"
    assert claimed[0].message_id == "1001-0"
    assert claimed[0].attempt == 2


@pytest.mark.asyncio
async def test_webhook_queue_claim_stale_returns_empty_when_group_disappears() -> None:
    assert await _queue(_ClaimNoGroupRedisStub()).claim_stale(
        consumer_name="worker-1",
        min_idle_ms=100,
        count=10,
    ) == []


@pytest.mark.asyncio
async def test_webhook_queue_retry_and_dead_letter_record_metrics_and_truncate_errors() -> None:
    retry_redis = _RetryRedisStub()
    retry_queue = _queue(retry_redis)
    message = WebhookStreamMessage("1000-0", 101, _update(101), 1000, 0)

    retried = await retry_queue.retry_or_dead(message, max_attempts=3, error_message="x" * 700)

    assert retried is True
    assert retry_redis.xadd_calls[0][0] == "dtb:webhook_ingress:updates"
    assert len(str(retry_redis.xadd_calls[0][1]["last_error"])) == 500
    assert retry_redis.incr_calls == ["dtb:webhook_ingress:metrics:failed_total"]

    dead_redis = _RetryRedisStub()
    dead_queue = _queue(dead_redis)
    dead = await dead_queue.retry_or_dead(
        WebhookStreamMessage("1002-0", 102, _update(102), 1000, 2),
        max_attempts=3,
        error_message="y" * 1200,
    )

    assert dead is False
    assert dead_redis.xadd_calls[0][0] == "dtb:webhook_ingress:dead"
    assert len(str(dead_redis.xadd_calls[0][1]["error"])) == 1000
    assert dead_redis.incr_calls == ["dtb:webhook_ingress:metrics:dead_total"]


@pytest.mark.asyncio
async def test_webhook_queue_stats_and_metric_samples_are_typed() -> None:
    redis_client = _StatsRedisStub()
    queue = _queue(redis_client)

    stats = await queue.stats()
    lag_samples = await queue.processing_lag_samples(limit=2)
    dispatch_samples = await queue.worker_dispatch_samples(limit=2)

    assert stats.queue_depth == 5
    assert stats.pending == 2
    assert stats.lag is None
    assert stats.processed_total == 7
    assert lag_samples == [12.5, 0.0]
    assert dispatch_samples == [3.25, 4.5]


@pytest.mark.asyncio
async def test_webhook_queue_stats_wraps_redis_errors() -> None:
    with pytest.raises(WebhookIngressQueueError, match="webhook_ingress_stats_unavailable"):
        await _queue(_StatsFailRedisStub()).stats()


def test_webhook_queue_parsers_reject_invalid_shapes() -> None:
    assert _parse_stream_batches(None) == []
    assert _parse_xautoclaim_result("bad") == []
    with pytest.raises(WebhookIngressQueueError, match="payload_invalid"):
        _decode_payload(["not", "json"])
    with pytest.raises(WebhookIngressQueueError, match="enqueue_result_invalid"):
        _parse_enqueue_result([1])


@pytest.mark.asyncio
async def test_webhook_queue_warm_loads_single_and_batch_lua_scripts() -> None:
    redis_client = _WarmRedisStub()
    queue = _queue(redis_client)

    await queue.warm()

    assert redis_client.group_created is True
    assert redis_client.loaded_scripts == 2


@pytest.mark.asyncio
async def test_webhook_queue_enqueue_update_reloads_lua_after_noscript() -> None:
    redis_client = _EvalRedisReloadStub()
    queue = _queue(redis_client)

    result = await queue.enqueue_update(_update(101))

    assert result.accepted is True
    assert result.update_id == 101
    assert result.stream_id == "1-0"
    assert redis_client.script_load_calls == 2


@pytest.mark.asyncio
async def test_webhook_queue_enqueue_updates_raises_when_batch_script_fails() -> None:
    redis_client = _BatchFailRedisStub()
    queue = _queue(redis_client)

    with pytest.raises(WebhookIngressQueueError, match="webhook_ingress_enqueue_unavailable"):
        await queue.enqueue_updates([_update(101)])


@pytest.mark.asyncio
async def test_webhook_queue_mark_processed_empty_batch_is_noop() -> None:
    redis_client = _StatsRedisStub()
    queue = _queue(redis_client)

    await queue.mark_processed_many([])

    assert not hasattr(redis_client, "pipeline_instance")


class _GroupRedisStub:
    def __init__(self, error: RedisError) -> None:
        self._error = error

    async def xgroup_create(self, *_args, **_kwargs) -> None:
        raise self._error


class _ReadRedisStub:
    def __init__(self) -> None:
        self.xreadgroup_calls: list[tuple[object, ...]] = []

    async def xgroup_create(self, *_args, **_kwargs) -> None:
        return None

    async def xreadgroup(self, group_name, consumer_name, *, streams, count, block):
        self.xreadgroup_calls.append((group_name, consumer_name, streams, count, block))
        return [
            (
                "dtb:webhook_ingress:updates",
                [
                    (
                        "1000-0",
                        {
                            "update_id": "101",
                            "payload": json.dumps(_update(101)),
                            "attempt": "0",
                        },
                    )
                ],
            )
        ]

    async def xautoclaim(self, *_args, **_kwargs):
        return [
            "0-0",
            [
                (
                    "1001-0",
                    {
                        "update_id": "102",
                        "payload": json.dumps(_update(102)),
                        "attempt": "2",
                    },
                )
            ],
        ]


class _ClaimNoGroupRedisStub:
    async def xgroup_create(self, *_args, **_kwargs) -> None:
        return None

    async def xautoclaim(self, *_args, **_kwargs):
        raise RedisError("NOGROUP")


class _RetryRedisStub:
    def __init__(self) -> None:
        self.xadd_calls: list[tuple[str, dict[str, object]]] = []
        self.xack_calls: list[tuple[str, str, str]] = []
        self.xdel_calls: list[tuple[str, str]] = []
        self.incr_calls: list[str] = []

    async def xadd(self, key: str, fields: dict[str, object]) -> str:
        self.xadd_calls.append((key, fields))
        return "1002-0"

    async def xack(self, stream_key: str, group_name: str, message_id: str) -> None:
        self.xack_calls.append((stream_key, group_name, message_id))

    async def xdel(self, stream_key: str, message_id: str) -> None:
        self.xdel_calls.append((stream_key, message_id))

    async def incr(self, key: str) -> None:
        self.incr_calls.append(key)


class _StatsRedisStub:
    async def xlen(self, key: str) -> int:
        return 1 if key.endswith(":dead") else 5

    async def xinfo_groups(self, _stream_key: str):
        return [{"name": "workers", "pending": 2, "lag": None}]

    async def xrange(self, _stream_key: str, *, count: int):
        return [("1000-0", {"enqueued_at_ms": "1000"})]

    async def get(self, key: str):
        values = {
            "dtb:webhook_ingress:metrics:processed_total": "7",
            "dtb:webhook_ingress:metrics:failed_total": "3",
            "dtb:webhook_ingress:metrics:dead_total": "1",
        }
        return values[key]

    async def lrange(self, key: str, start: int, end: int):
        if key.endswith(":processing_lag_ms"):
            return ["12.5", None]
        return ["3.25", "4.5"]


class _StatsFailRedisStub:
    async def xlen(self, _key: str) -> int:
        raise RedisError("down")


class _WarmRedisStub:
    def __init__(self) -> None:
        self.group_created = False
        self.loaded_scripts = 0

    async def xgroup_create(self, *_args, **_kwargs) -> None:
        self.group_created = True

    async def script_load(self, _script: str) -> str:
        self.loaded_scripts += 1
        return f"sha-{self.loaded_scripts}"


class _EvalRedisReloadStub:
    def __init__(self) -> None:
        self.script_load_calls = 0
        self.evalsha_calls = 0

    async def script_load(self, _script: str) -> str:
        self.script_load_calls += 1
        return f"sha-{self.script_load_calls}"

    async def evalsha(self, *_args: object):
        self.evalsha_calls += 1
        if self.evalsha_calls == 1:
            raise NoScriptError("missing")
        return [1, "1-0"]


class _BatchFailRedisStub:
    async def script_load(self, _script: str) -> str:
        return "sha"

    async def evalsha(self, *_args: object):
        raise RedisError("down")


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
