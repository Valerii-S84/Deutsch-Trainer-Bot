from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
import json
from time import time
from typing import Any

from redis.asyncio import Redis
from redis.exceptions import NoScriptError, RedisError


ENQUEUE_ANSWER_EVENT_SCRIPT = """
local event_key = KEYS[1]
local question_key = KEYS[2]
local result_key = KEYS[3]
local stream_key = KEYS[4]
local ttl_seconds = tonumber(ARGV[1])
local event_payload = ARGV[2]
local result_payload = ARGV[3]
local answer_event_id = ARGV[4]
local redis_time = redis.call('TIME')
local enqueued_at_ms = (tonumber(redis_time[1]) * 1000) + math.floor(tonumber(redis_time[2]) / 1000)

local existing_result_key = redis.call('GET', event_key)
if existing_result_key then
  return {0, 'duplicate_event', redis.call('GET', existing_result_key) or '', ''}
end

existing_result_key = redis.call('GET', question_key)
if existing_result_key then
  return {0, 'duplicate_question', redis.call('GET', existing_result_key) or '', ''}
end

local event_created = redis.call('SET', event_key, result_key, 'EX', ttl_seconds, 'NX')
if not event_created then
  existing_result_key = redis.call('GET', event_key)
  return {0, 'duplicate_event', redis.call('GET', existing_result_key) or '', ''}
end

local question_created = redis.call('SET', question_key, result_key, 'EX', ttl_seconds, 'NX')
if not question_created then
  redis.call('DEL', event_key)
  existing_result_key = redis.call('GET', question_key)
  return {0, 'duplicate_question', redis.call('GET', existing_result_key) or '', ''}
end

redis.call('SET', result_key, result_payload, 'EX', ttl_seconds)
local stream_id = redis.call(
  'XADD',
  stream_key,
  '*',
  'payload',
  event_payload,
  'answer_event_id',
  answer_event_id,
  'enqueued_at_ms',
  enqueued_at_ms,
  'attempt',
  '0'
)
return {1, 'queued', result_payload, stream_id}
"""


@dataclass(frozen=True, slots=True)
class AnswerPersistEnqueueResult:
    accepted: bool
    duplicate: bool
    duplicate_reason: str | None
    answer_event_id: str
    result_payload: dict[str, Any]
    stream_id: str | None = None


@dataclass(frozen=True, slots=True)
class AnswerPersistEnqueueItem:
    answer_event_id: str
    question_dedupe_id: str
    event_payload: dict[str, Any]
    result_payload: dict[str, Any]


@dataclass(frozen=True, slots=True)
class AnswerPersistenceMessage:
    message_id: str
    answer_event_id: str
    payload: dict[str, Any]
    enqueued_at_ms: int
    attempt: int


@dataclass(frozen=True, slots=True)
class AnswerPersistenceStats:
    stream_length: int
    dead_letter_length: int
    pending: int
    lag: int | None
    oldest_lag_ms: int
    persisted_total: int
    failed_total: int
    dead_total: int

    @property
    def queue_depth(self) -> int:
        if self.lag is None:
            return self.stream_length
        return max(self.stream_length, self.pending + self.lag)


class AnswerPersistenceQueueError(RuntimeError):
    """Raised when Redis cannot safely enqueue or consume answer persistence events."""


@dataclass(frozen=True, slots=True)
class AnswerPersistenceQueueSettings:
    stream_key: str
    group_name: str
    dead_letter_key: str
    event_key_prefix: str
    question_key_prefix: str
    result_key_prefix: str
    metrics_key_prefix: str
    ttl_seconds: int
    processing_lag_sample_size: int


def create_answer_persistence_queue(settings: Any, redis_client: Redis) -> "AnswerPersistenceQueue":
    return AnswerPersistenceQueue(
        redis_client,
        AnswerPersistenceQueueSettings(
            stream_key=settings.answer_persist_stream_key,
            group_name=settings.answer_persist_group_name,
            dead_letter_key=settings.answer_persist_dead_letter_key,
            event_key_prefix=settings.answer_persist_event_key_prefix,
            question_key_prefix=settings.answer_persist_question_key_prefix,
            result_key_prefix=settings.answer_persist_result_key_prefix,
            metrics_key_prefix=settings.answer_persist_metrics_key_prefix,
            ttl_seconds=settings.telegram_duplicate_update_ttl_seconds,
            processing_lag_sample_size=settings.answer_persist_processing_lag_sample_size,
        ),
    )


class AnswerPersistenceQueue:
    def __init__(
        self,
        redis_client: Redis,
        settings: AnswerPersistenceQueueSettings,
    ) -> None:
        self._redis = redis_client
        self._stream_key = settings.stream_key
        self._group_name = settings.group_name
        self._dead_letter_key = settings.dead_letter_key
        self._event_key_prefix = settings.event_key_prefix.rstrip(":")
        self._question_key_prefix = settings.question_key_prefix.rstrip(":")
        self._result_key_prefix = settings.result_key_prefix.rstrip(":")
        self._metrics_key_prefix = settings.metrics_key_prefix.rstrip(":")
        self._ttl_seconds = max(1, settings.ttl_seconds)
        self._processing_lag_sample_size = max(1, settings.processing_lag_sample_size)
        self._enqueue_script_sha: str | None = None
        self._enqueue_script_lock = asyncio.Lock()

    @property
    def stream_key(self) -> str:
        return self._stream_key

    @property
    def dead_letter_key(self) -> str:
        return self._dead_letter_key

    @property
    def group_name(self) -> str:
        return self._group_name

    async def ensure_group(self) -> None:
        try:
            await self._redis.xgroup_create(self._stream_key, self._group_name, id="0-0", mkstream=True)
        except RedisError as exc:
            if "BUSYGROUP" in str(exc):
                return
            raise AnswerPersistenceQueueError("answer_persistence_group_unavailable") from exc

    async def warm(self) -> None:
        await self.ensure_group()
        await self._enqueue_script_sha_value()

    async def enqueue_answer_event(
        self,
        *,
        answer_event_id: str,
        question_dedupe_id: str,
        event_payload: dict[str, Any],
        result_payload: dict[str, Any],
    ) -> AnswerPersistEnqueueResult:
        item = AnswerPersistEnqueueItem(
            answer_event_id=answer_event_id,
            question_dedupe_id=question_dedupe_id,
            event_payload=event_payload,
            result_payload=result_payload,
        )
        try:
            result = await self._enqueue_one_evalsha(item)
        except RedisError as exc:
            raise AnswerPersistenceQueueError("answer_persistence_enqueue_unavailable") from exc
        return self._enqueue_result(item, result)

    async def enqueue_answer_events(
        self,
        items: Sequence[AnswerPersistEnqueueItem],
    ) -> list[AnswerPersistEnqueueResult]:
        if not items:
            return []
        try:
            return await self._enqueue_many_evalsha(items)
        except NoScriptError:
            self._enqueue_script_sha = None
            return await self._enqueue_many_evalsha(items)
        except RedisError as exc:
            raise AnswerPersistenceQueueError("answer_persistence_enqueue_unavailable") from exc

    def _enqueue_result(
        self,
        item: AnswerPersistEnqueueItem,
        result: object,
    ) -> AnswerPersistEnqueueResult:
        encoded_result = _encode_payload(item.result_payload)
        accepted, reason, duplicate_result, stream_id = _parse_enqueue_result(result)
        return AnswerPersistEnqueueResult(
            accepted=accepted,
            duplicate=not accepted,
            duplicate_reason=None if accepted else reason,
            answer_event_id=item.answer_event_id,
            result_payload=_decode_payload(duplicate_result or encoded_result),
            stream_id=stream_id if accepted else None,
        )

    async def read_batch(
        self,
        *,
        consumer_name: str,
        count: int,
        block_ms: int,
    ) -> list[AnswerPersistenceMessage]:
        await self.ensure_group()
        try:
            batches = await self._redis.xreadgroup(
                self._group_name,
                consumer_name,
                streams={self._stream_key: ">"},
                count=max(1, count),
                block=max(1, block_ms),
            )
        except RedisError as exc:
            raise AnswerPersistenceQueueError("answer_persistence_read_unavailable") from exc
        return _parse_stream_batches(batches)

    async def claim_stale(
        self,
        *,
        consumer_name: str,
        min_idle_ms: int,
        count: int,
    ) -> list[AnswerPersistenceMessage]:
        await self.ensure_group()
        try:
            result = await self._redis.xautoclaim(
                self._stream_key,
                self._group_name,
                consumer_name,
                min_idle_time=max(1, min_idle_ms),
                start_id="0-0",
                count=max(1, count),
            )
        except RedisError as exc:
            if "NOGROUP" in str(exc):
                return []
            raise AnswerPersistenceQueueError("answer_persistence_claim_unavailable") from exc
        return _parse_xautoclaim_result(result)

    async def mark_persisted(self, messages: Sequence[AnswerPersistenceMessage]) -> None:
        if not messages:
            return
        now_ms = await _redis_now_ms(self._redis)
        pipe = self._redis.pipeline()
        message_ids = [message.message_id for message in messages]
        pipe.xack(self._stream_key, self._group_name, *message_ids)
        pipe.xdel(self._stream_key, *message_ids)
        pipe.incrby(self._metric_key("persisted_total"), len(messages))
        for message in messages:
            pipe.lpush(self._metric_key("processing_lag_ms"), str(max(0, now_ms - message.enqueued_at_ms)))
        pipe.ltrim(self._metric_key("processing_lag_ms"), 0, self._processing_lag_sample_size - 1)
        await pipe.execute()

    async def retry_or_dead(
        self,
        message: AnswerPersistenceMessage,
        *,
        max_attempts: int,
        error_message: str,
    ) -> bool:
        next_attempt = message.attempt + 1
        if next_attempt >= max(1, max_attempts):
            await self._dead_letter(message, error_message=error_message, attempts=next_attempt)
            await self._redis.incr(self._metric_key("dead_total"))
            return False
        await self._retry(message, error_message=error_message, attempt=next_attempt)
        await self._redis.incr(self._metric_key("failed_total"))
        return True

    async def stats(self) -> AnswerPersistenceStats:
        try:
            stream_length = int(await self._redis.xlen(self._stream_key))
            dead_letter_length = int(await self._redis.xlen(self._dead_letter_key))
            pending, lag = await self._group_pending_and_lag()
            oldest_lag_ms = await self._oldest_lag_ms()
            persisted_total = await self._metric_int("persisted_total")
            failed_total = await self._metric_int("failed_total")
            dead_total = await self._metric_int("dead_total")
        except RedisError as exc:
            raise AnswerPersistenceQueueError("answer_persistence_stats_unavailable") from exc
        return AnswerPersistenceStats(
            stream_length=stream_length,
            dead_letter_length=dead_letter_length,
            pending=pending,
            lag=lag,
            oldest_lag_ms=oldest_lag_ms,
            persisted_total=persisted_total,
            failed_total=failed_total,
            dead_total=dead_total,
        )

    async def _enqueue_evalsha(self, *args: object) -> object:
        script_sha = await self._enqueue_script_sha_value()
        try:
            return await self._redis.evalsha(script_sha, 4, *args)
        except NoScriptError:
            self._enqueue_script_sha = None
            script_sha = await self._enqueue_script_sha_value()
            return await self._redis.evalsha(script_sha, 4, *args)

    async def _enqueue_one_evalsha(self, item: AnswerPersistEnqueueItem) -> object:
        return await self._enqueue_evalsha(*self._enqueue_args(item))

    async def _enqueue_many_evalsha(
        self,
        items: Sequence[AnswerPersistEnqueueItem],
    ) -> list[AnswerPersistEnqueueResult]:
        script_sha = await self._enqueue_script_sha_value()
        pipe = self._redis.pipeline(transaction=False)
        for item in items:
            pipe.evalsha(script_sha, 4, *self._enqueue_args(item))
        raw_results = await pipe.execute()
        return [self._enqueue_result(item, result) for item, result in zip(items, raw_results)]

    def _enqueue_args(self, item: AnswerPersistEnqueueItem) -> tuple[object, ...]:
        return (
            self._event_key(item.answer_event_id),
            self._question_key(item.question_dedupe_id),
            self._result_key(item.answer_event_id),
            self._stream_key,
            self._ttl_seconds,
            _encode_payload(item.event_payload),
            _encode_payload(item.result_payload),
            item.answer_event_id,
        )

    async def _enqueue_script_sha_value(self) -> str:
        if self._enqueue_script_sha is not None:
            return self._enqueue_script_sha
        async with self._enqueue_script_lock:
            if self._enqueue_script_sha is None:
                self._enqueue_script_sha = str(await self._redis.script_load(ENQUEUE_ANSWER_EVENT_SCRIPT))
            return self._enqueue_script_sha

    async def _retry(self, message: AnswerPersistenceMessage, *, error_message: str, attempt: int) -> None:
        await self._redis.xadd(
            self._stream_key,
            {
                "payload": _encode_payload(message.payload),
                "answer_event_id": message.answer_event_id,
                "enqueued_at_ms": str(message.enqueued_at_ms),
                "attempt": str(attempt),
                "last_error": error_message[:500],
                "original_message_id": message.message_id,
            },
        )
        await self._ack_delete(message.message_id)

    async def _dead_letter(self, message: AnswerPersistenceMessage, *, error_message: str, attempts: int) -> None:
        await self._redis.xadd(
            self._dead_letter_key,
            {
                "payload": _encode_payload(message.payload),
                "answer_event_id": message.answer_event_id,
                "enqueued_at_ms": str(message.enqueued_at_ms),
                "attempt": str(attempts),
                "failed_at_ms": str(_now_ms()),
                "error": error_message[:1000],
                "original_message_id": message.message_id,
            },
        )
        await self._ack_delete(message.message_id)

    async def _ack_delete(self, message_id: str) -> None:
        await self._redis.xack(self._stream_key, self._group_name, message_id)
        await self._redis.xdel(self._stream_key, message_id)

    async def _group_pending_and_lag(self) -> tuple[int, int | None]:
        try:
            groups = await self._redis.xinfo_groups(self._stream_key)
        except RedisError as exc:
            if "no such key" in str(exc).lower():
                return 0, 0
            raise
        for group in groups:
            if str(group.get("name")) == self._group_name:
                pending = _int_value(group.get("pending"))
                lag_raw = group.get("lag")
                return pending, None if lag_raw is None else _int_value(lag_raw)
        return 0, 0

    async def _oldest_lag_ms(self) -> int:
        rows = await self._redis.xrange(self._stream_key, count=1)
        if not rows:
            return 0
        _, fields = rows[0]
        return max(0, _now_ms() - _int_value(fields.get("enqueued_at_ms")))

    async def _metric_int(self, name: str) -> int:
        value = await self._redis.get(self._metric_key(name))
        return _int_value(value)

    def _event_key(self, answer_event_id: str) -> str:
        return f"{self._event_key_prefix}:{answer_event_id}"

    def _question_key(self, question_dedupe_id: str) -> str:
        return f"{self._question_key_prefix}:{question_dedupe_id}"

    def _result_key(self, answer_event_id: str) -> str:
        return f"{self._result_key_prefix}:{answer_event_id}"

    def _metric_key(self, name: str) -> str:
        return f"{self._metrics_key_prefix}:{name}"


def _encode_payload(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _decode_payload(raw_payload: object) -> dict[str, Any]:
    if not isinstance(raw_payload, str):
        raise AnswerPersistenceQueueError("answer_persistence_payload_invalid")
    payload = json.loads(raw_payload)
    if not isinstance(payload, dict):
        raise AnswerPersistenceQueueError("answer_persistence_payload_invalid")
    return payload


def _now_ms() -> int:
    return int(time() * 1000)


async def _redis_now_ms(redis_client: Redis) -> int:
    seconds, microseconds = await redis_client.time()
    return (int(seconds) * 1000) + (int(microseconds) // 1000)


def _parse_enqueue_result(result: object) -> tuple[bool, str | None, str | None, str | None]:
    if not isinstance(result, (list, tuple)) or len(result) != 4:
        raise AnswerPersistenceQueueError("answer_persistence_enqueue_result_invalid")
    accepted = bool(int(result[0]))
    reason = str(result[1]) if result[1] else None
    result_payload = str(result[2]) if result[2] else None
    stream_id = str(result[3]) if result[3] else None
    return accepted, reason, result_payload, stream_id


def _parse_stream_batches(batches: object) -> list[AnswerPersistenceMessage]:
    messages: list[AnswerPersistenceMessage] = []
    if not isinstance(batches, list):
        return messages
    for _, rows in batches:
        for message_id, fields in rows:
            messages.append(_stream_message(str(message_id), fields))
    return messages


def _parse_xautoclaim_result(result: object) -> list[AnswerPersistenceMessage]:
    if not isinstance(result, (list, tuple)) or len(result) < 2:
        return []
    rows = result[1]
    return [_stream_message(str(message_id), fields) for message_id, fields in rows]


def _stream_message(message_id: str, fields: dict[str, object]) -> AnswerPersistenceMessage:
    return AnswerPersistenceMessage(
        message_id=message_id,
        answer_event_id=str(fields.get("answer_event_id") or ""),
        payload=_decode_payload(fields.get("payload")),
        enqueued_at_ms=_stream_id_ms(message_id) or _int_value(fields.get("enqueued_at_ms")),
        attempt=_int_value(fields.get("attempt")),
    )


def _int_value(value: object) -> int:
    if value is None:
        return 0
    return int(value)


def _stream_id_ms(message_id: str) -> int:
    raw_ms, _, _sequence = message_id.partition("-")
    try:
        return int(raw_ms)
    except ValueError:
        return 0
