from __future__ import annotations

import json

import pytest
from redis.exceptions import RedisError

from app.runtime.answer_persistence_queue import (
    AnswerPersistEnqueueItem,
    AnswerPersistenceMessage,
    AnswerPersistenceQueue,
    AnswerPersistenceQueueError,
    AnswerPersistenceQueueSettings,
)


@pytest.mark.asyncio
async def test_enqueue_answer_events_batches_with_set_nx_dedupe_keys_and_stream_payload() -> None:
    redis_client = _RedisPipelineStub([[1, "queued", _encoded_result(101), "1-0"]])
    queue = _queue(redis_client)
    item = _item(101)

    results = await queue.enqueue_answer_events([item])

    assert results[0].accepted is True
    assert results[0].stream_id == "1-0"
    assert redis_client.script_load_calls == 1
    pipe = redis_client.pipeline_instance
    assert pipe.evalsha_calls[0][0:2] == ("sha-answer", 4)
    assert pipe.evalsha_calls[0][2:6] == (
        "dtb:answer_persist:event:update:101",
        "dtb:answer_persist:question:1:tok",
        "dtb:answer_persist:result:update:101",
        "dtb:answer_persist:events",
    )
    assert json.loads(pipe.evalsha_calls[0][7])["telegram_update_id"] == 101


@pytest.mark.asyncio
async def test_duplicate_answer_event_returns_cached_result_without_stream_id() -> None:
    redis_client = _RedisPipelineStub([[0, "duplicate_event", _encoded_result(101), ""]])
    queue = _queue(redis_client)

    results = await queue.enqueue_answer_events([_item(101)])

    assert results[0].accepted is False
    assert results[0].duplicate is True
    assert results[0].duplicate_reason == "duplicate_event"
    assert results[0].stream_id is None
    assert results[0].result_payload["telegram_update_id"] == 101


@pytest.mark.asyncio
async def test_answer_enqueue_redis_error_is_not_silent_lost_event() -> None:
    redis_client = _FailingRedisStub()
    queue = _queue(redis_client)

    with pytest.raises(AnswerPersistenceQueueError, match="answer_persistence_enqueue_unavailable"):
        await queue.enqueue_answer_event(
            answer_event_id="update:101",
            question_dedupe_id="1:tok",
            event_payload=_event_payload(101),
            result_payload=_result_payload(101),
        )


@pytest.mark.asyncio
async def test_mark_persisted_acks_after_successful_persistence_batch() -> None:
    redis_client = _RedisAckStub()
    queue = _queue(redis_client)
    messages = [
        AnswerPersistenceMessage("1000-0", "update:101", _event_payload(101), 1000, 0),
        AnswerPersistenceMessage("1001-0", "update:102", _event_payload(102), 1001, 0),
    ]

    await queue.mark_persisted(messages)

    assert redis_client.pipeline_instance.calls[0] == ("xack", "dtb:answer_persist:events", "answer-persist", ("1000-0", "1001-0"))
    assert redis_client.pipeline_instance.calls[1] == ("xdel", "dtb:answer_persist:events", ("1000-0", "1001-0"))
    assert ("incrby", "dtb:answer_persist:metrics:persisted_total", 2) in redis_client.pipeline_instance.calls


@pytest.mark.asyncio
async def test_retry_or_dead_moves_permanent_failure_to_dlq() -> None:
    redis_client = _RedisRetryStub()
    queue = _queue(redis_client)
    message = AnswerPersistenceMessage("1000-0", "update:101", _event_payload(101), 1000, 4)

    retried = await queue.retry_or_dead(message, max_attempts=5, error_message="db down")

    assert retried is False
    assert redis_client.xadd_calls[0][0] == "dtb:answer_persist:dead"
    assert redis_client.xack_calls == [("dtb:answer_persist:events", "answer-persist", "1000-0")]
    assert redis_client.incr_calls == ["dtb:answer_persist:metrics:dead_total"]


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


def _item(update_id: int) -> AnswerPersistEnqueueItem:
    return AnswerPersistEnqueueItem(
        answer_event_id=f"update:{update_id}",
        question_dedupe_id="1:tok",
        event_payload=_event_payload(update_id),
        result_payload=_result_payload(update_id),
    )


def _event_payload(update_id: int) -> dict[str, object]:
    return {
        "answer_event_id": f"update:{update_id}",
        "telegram_update_id": update_id,
        "telegram_user_id": 700001,
        "user_id": 1,
        "session_id": 1,
        "item_id": "q1",
        "level": "A1",
        "selected_answer": "a1",
        "correct_answer": "a2",
        "is_correct": False,
        "session_type": "regular",
        "session_completed": False,
        "answered_count": 1,
        "correct_answers": 0,
        "total_questions": 5,
    }


def _result_payload(update_id: int) -> dict[str, object]:
    return {"telegram_update_id": update_id, "is_duplicate": False}


def _encoded_result(update_id: int) -> str:
    return json.dumps(_result_payload(update_id), separators=(",", ":"))


class _RedisPipelineStub:
    def __init__(self, results: list[list[object]]) -> None:
        self._results = results
        self.script_load_calls = 0
        self.pipeline_instance = _EvalPipelineStub(results)

    async def script_load(self, _script: str) -> str:
        self.script_load_calls += 1
        return "sha-answer"

    def pipeline(self, *, transaction: bool = True):
        assert transaction is False
        return self.pipeline_instance


class _EvalPipelineStub:
    def __init__(self, results: list[list[object]]) -> None:
        self._results = results
        self.evalsha_calls: list[tuple[object, ...]] = []

    def evalsha(self, *args: object) -> None:
        self.evalsha_calls.append(args)

    async def execute(self) -> list[list[object]]:
        return self._results


class _FailingRedisStub:
    async def script_load(self, _script: str) -> str:
        return "sha-answer"

    async def evalsha(self, *args: object) -> object:
        del args
        raise RedisError("down")


class _RedisAckStub:
    def __init__(self) -> None:
        self.pipeline_instance = _AckPipelineSpy()

    async def time(self) -> tuple[int, int]:
        return 2, 0

    def pipeline(self):
        return self.pipeline_instance


class _AckPipelineSpy:
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


class _RedisRetryStub:
    def __init__(self) -> None:
        self.xadd_calls: list[tuple[str, dict[str, object]]] = []
        self.xack_calls: list[tuple[str, str, str]] = []
        self.xdel_calls: list[tuple[str, str]] = []
        self.incr_calls: list[str] = []

    async def xadd(self, key: str, fields: dict[str, object]) -> str:
        self.xadd_calls.append((key, fields))
        return "dead-1"

    async def xack(self, stream_key: str, group_name: str, message_id: str) -> None:
        self.xack_calls.append((stream_key, group_name, message_id))

    async def xdel(self, stream_key: str, message_id: str) -> None:
        self.xdel_calls.append((stream_key, message_id))

    async def incr(self, key: str) -> None:
        self.incr_calls.append(key)
