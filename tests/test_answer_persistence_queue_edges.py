from __future__ import annotations

import json

import pytest
from redis.exceptions import NoScriptError, RedisError

from app.runtime.answer_persistence_queue import (
    AnswerPersistEnqueueItem,
    AnswerPersistenceMessage,
    AnswerPersistenceQueue,
    AnswerPersistenceQueueError,
    AnswerPersistenceQueueSettings,
    _decode_payload,
    _parse_enqueue_result,
    _parse_stream_batches,
    _parse_xautoclaim_result,
)
from tests.test_answer_persistence_queue import _event_payload


@pytest.mark.asyncio
async def test_answer_queue_ensure_group_ignores_existing_group_and_wraps_other_errors() -> None:
    busy_queue = _queue(_GroupRedisStub(RedisError("BUSYGROUP Consumer Group name already exists")))
    failing_queue = _queue(_GroupRedisStub(RedisError("no redis")))

    await busy_queue.ensure_group()
    with pytest.raises(AnswerPersistenceQueueError, match="answer_persistence_group_unavailable"):
        await failing_queue.ensure_group()


@pytest.mark.asyncio
async def test_answer_queue_read_batch_and_claim_stale_parse_stream_messages() -> None:
    redis_client = _ReadRedisStub()
    queue = _queue(redis_client)

    messages = await queue.read_batch(consumer_name="worker-1", count=0, block_ms=0)
    claimed = await queue.claim_stale(consumer_name="worker-1", min_idle_ms=0, count=0)

    assert redis_client.xreadgroup_calls == [
        ("answer-persist", "worker-1", {"dtb:answer_persist:events": ">"}, 1, 1)
    ]
    assert messages[0].message_id == "1000-0"
    assert messages[0].answer_event_id == "update:101"
    assert messages[0].payload["telegram_update_id"] == 101
    assert claimed[0].message_id == "1001-0"
    assert claimed[0].attempt == 2


@pytest.mark.asyncio
async def test_answer_queue_claim_stale_returns_empty_when_group_disappears() -> None:
    queue = _queue(_ClaimNoGroupRedisStub())

    assert await queue.claim_stale(consumer_name="worker-1", min_idle_ms=100, count=10) == []


@pytest.mark.asyncio
async def test_answer_queue_retry_path_requeues_and_truncates_error() -> None:
    redis_client = _RetryRedisStub()
    queue = _queue(redis_client)
    message = AnswerPersistenceMessage("1000-0", "update:101", _event_payload(101), 1000, 0)

    retried = await queue.retry_or_dead(message, max_attempts=3, error_message="x" * 700)

    assert retried is True
    assert redis_client.xadd_calls[0][0] == "dtb:answer_persist:events"
    assert len(str(redis_client.xadd_calls[0][1]["last_error"])) == 500
    assert redis_client.incr_calls == ["dtb:answer_persist:metrics:failed_total"]


@pytest.mark.asyncio
async def test_answer_queue_stats_use_stream_length_when_lag_is_unknown() -> None:
    redis_client = _StatsRedisStub()
    queue = _queue(redis_client)

    stats = await queue.stats()

    assert stats.stream_length == 5
    assert stats.dead_letter_length == 1
    assert stats.pending == 2
    assert stats.lag is None
    assert stats.queue_depth == 5
    assert stats.persisted_total == 7
    assert stats.failed_total == 3
    assert stats.dead_total == 1


def test_answer_queue_parsers_reject_invalid_payload_shapes() -> None:
    assert _parse_stream_batches(None) == []
    assert _parse_xautoclaim_result("bad") == []
    with pytest.raises(AnswerPersistenceQueueError, match="payload_invalid"):
        _decode_payload(["not", "json"])
    with pytest.raises(AnswerPersistenceQueueError, match="enqueue_result_invalid"):
        _parse_enqueue_result([1, "queued"])


@pytest.mark.asyncio
async def test_answer_queue_enqueue_single_reloads_lua_after_noscript() -> None:
    redis_client = _EvalRedisReloadStub()
    queue = _queue(redis_client)

    result = await queue.enqueue_answer_event(
        answer_event_id="update:101",
        question_dedupe_id="1:tok",
        event_payload=_event_payload(101),
        result_payload={"ok": True},
    )

    assert result.accepted is True
    assert result.stream_id == "1-0"
    assert redis_client.script_load_calls == 2
    assert redis_client.evalsha_calls[0][0] == "sha-1"
    assert redis_client.evalsha_calls[1][0] == "sha-2"


@pytest.mark.asyncio
async def test_answer_queue_enqueue_many_empty_and_noscript_retry() -> None:
    queue = _queue(_EvalRedisReloadStub())
    assert await queue.enqueue_answer_events([]) == []

    redis_client = _PipelineNoScriptRedisStub()
    queue = _queue(redis_client)
    results = await queue.enqueue_answer_events(
        [
            AnswerPersistEnqueueItem(
                answer_event_id="update:101",
                question_dedupe_id="1:tok",
                event_payload=_event_payload(101),
                result_payload={"ok": True},
            )
        ]
    )

    assert results[0].accepted is True
    assert redis_client.script_load_calls == 2
    assert redis_client.pipeline_calls == 2


@pytest.mark.asyncio
async def test_answer_queue_mark_persisted_empty_batch_is_noop() -> None:
    redis_client = _StatsRedisStub()
    queue = _queue(redis_client)

    await queue.mark_persisted([])

    assert not hasattr(redis_client, "pipeline_instance")


@pytest.mark.asyncio
async def test_answer_queue_stats_handles_missing_group_and_wraps_failures() -> None:
    missing_group_queue = _queue(_MissingGroupStatsRedisStub())
    stats = await missing_group_queue.stats()

    assert stats.pending == 0
    assert stats.lag == 0
    assert stats.queue_depth == 2

    with pytest.raises(AnswerPersistenceQueueError, match="answer_persistence_stats_unavailable"):
        await _queue(_StatsFailRedisStub()).stats()


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
                "dtb:answer_persist:events",
                [
                    (
                        "1000-0",
                        {
                            "answer_event_id": "update:101",
                            "payload": json.dumps(_event_payload(101)),
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
                        "answer_event_id": "update:102",
                        "payload": json.dumps(_event_payload(102)),
                        "attempt": "2",
                    },
                )
            ],
        ]


class _ClaimNoGroupRedisStub:
    async def xgroup_create(self, *_args, **_kwargs) -> None:
        return None

    async def xautoclaim(self, *_args, **_kwargs):
        raise RedisError("NOGROUP no such key")


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
        return [{"name": "answer-persist", "pending": 2, "lag": None}]

    async def xrange(self, _stream_key: str, *, count: int):
        return [("1000-0", {"enqueued_at_ms": "1000"})]

    async def get(self, key: str):
        values = {
            "dtb:answer_persist:metrics:persisted_total": "7",
            "dtb:answer_persist:metrics:failed_total": "3",
            "dtb:answer_persist:metrics:dead_total": "1",
        }
        return values[key]


class _EvalRedisReloadStub:
    def __init__(self) -> None:
        self.script_load_calls = 0
        self.evalsha_calls: list[tuple[object, ...]] = []

    async def script_load(self, _script: str) -> str:
        self.script_load_calls += 1
        return f"sha-{self.script_load_calls}"

    async def evalsha(self, *args: object):
        self.evalsha_calls.append(args)
        if len(self.evalsha_calls) == 1:
            raise NoScriptError("missing")
        return [1, "queued", json.dumps({"ok": True}), "1-0"]


class _PipelineNoScriptRedisStub:
    def __init__(self) -> None:
        self.script_load_calls = 0
        self.pipeline_calls = 0

    async def script_load(self, _script: str) -> str:
        self.script_load_calls += 1
        return f"sha-{self.script_load_calls}"

    def pipeline(self, *, transaction: bool = True):
        assert transaction is False
        self.pipeline_calls += 1
        return _NoScriptThenOkPipeline(raise_missing=self.pipeline_calls == 1)


class _NoScriptThenOkPipeline:
    def __init__(self, *, raise_missing: bool) -> None:
        self._raise_missing = raise_missing

    def evalsha(self, *_args: object) -> None:
        return None

    async def execute(self):
        if self._raise_missing:
            raise NoScriptError("missing")
        return [[1, "queued", json.dumps({"ok": True}), "1-0"]]


class _MissingGroupStatsRedisStub:
    async def xlen(self, key: str) -> int:
        return 0 if key.endswith(":dead") else 2

    async def xinfo_groups(self, _stream_key: str):
        return []

    async def xrange(self, _stream_key: str, *, count: int):
        return []

    async def get(self, _key: str):
        return None


class _StatsFailRedisStub:
    async def xlen(self, _key: str) -> int:
        raise RedisError("down")


def _queue(redis_client) -> AnswerPersistenceQueue:
    return AnswerPersistenceQueue(
        redis_client,
        AnswerPersistenceQueueSettings(
            stream_key="dtb:answer_persist:events",
            group_name="answer-persist",
            dead_letter_key="dtb:answer_persist:dead",
            event_key_prefix="dtb:answer_persist:event",
            question_key_prefix="dtb:answer_persist:question",
            result_key_prefix="dtb:answer_persist:result",
            metrics_key_prefix="dtb:answer_persist:metrics",
            ttl_seconds=300,
            processing_lag_sample_size=100,
        ),
    )
