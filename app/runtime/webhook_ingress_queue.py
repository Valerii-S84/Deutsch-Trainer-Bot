from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
import json
from time import time
from typing import Any

from redis.asyncio import Redis
from redis.exceptions import NoScriptError, RedisError

from app.runtime.webhook_ingress_lua import ENQUEUE_UPDATE_BATCH_SCRIPT, ENQUEUE_UPDATE_SCRIPT


@dataclass(frozen=True, slots=True)
class WebhookEnqueueResult:
    accepted: bool
    duplicate: bool
    update_id: int
    stream_id: str | None = None


@dataclass(frozen=True, slots=True)
class WebhookStreamMessage:
    message_id: str
    update_id: int
    payload: dict[str, Any]
    enqueued_at_ms: int
    attempt: int


@dataclass(frozen=True, slots=True)
class WebhookIngressQueueStats:
    stream_length: int
    dead_letter_length: int
    pending: int
    lag: int | None
    oldest_lag_ms: int
    processed_total: int
    failed_total: int
    dead_total: int

    @property
    def queue_depth(self) -> int:
        if self.lag is None:
            return self.stream_length
        return max(self.stream_length, self.pending + self.lag)


class WebhookIngressQueueError(RuntimeError):
    """Raised when Redis cannot safely persist or consume webhook updates."""


class InvalidWebhookUpdateError(ValueError):
    """Raised when a Telegram webhook update is not minimally valid."""


@dataclass(frozen=True, slots=True)
class WebhookIngressQueueSettings:
    stream_key: str
    group_name: str
    dead_letter_key: str
    dedupe_key_prefix: str
    metrics_key_prefix: str
    dedupe_ttl_seconds: int
    processing_lag_sample_size: int


@dataclass(frozen=True, slots=True)
class _PreparedWebhookUpdate:
    update_id: int
    dedupe_key: str
    payload: str


class WebhookIngressQueue:
    def __init__(
        self,
        redis_client: Redis,
        settings: WebhookIngressQueueSettings,
    ) -> None:
        self._redis = redis_client
        self._stream_key = settings.stream_key
        self._group_name = settings.group_name
        self._dead_letter_key = settings.dead_letter_key
        self._dedupe_key_prefix = settings.dedupe_key_prefix.rstrip(":")
        self._metrics_key_prefix = settings.metrics_key_prefix.rstrip(":")
        self._dedupe_ttl_seconds = max(1, settings.dedupe_ttl_seconds)
        self._processing_lag_sample_size = max(1, settings.processing_lag_sample_size)
        self._enqueue_script_sha: str | None = None
        self._enqueue_batch_script_sha: str | None = None
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
            raise WebhookIngressQueueError("webhook_ingress_group_unavailable") from exc

    async def warm(self) -> None:
        await self.ensure_group()
        await self._enqueue_script_sha_value()
        await self._enqueue_batch_script_sha_value()

    async def enqueue_update(self, update: dict[str, Any]) -> WebhookEnqueueResult:
        prepared = _prepare_update(update, dedupe_key_prefix=self._dedupe_key_prefix)
        try:
            result = await self._enqueue_evalsha(
                prepared.dedupe_key,
                self._stream_key,
                self._dedupe_ttl_seconds,
                prepared.payload,
                str(prepared.update_id),
                "0",
            )
        except RedisError as exc:
            raise WebhookIngressQueueError("webhook_ingress_enqueue_unavailable") from exc

        accepted, stream_id = _parse_enqueue_result(result)
        return WebhookEnqueueResult(
            accepted=accepted,
            duplicate=not accepted,
            update_id=prepared.update_id,
            stream_id=stream_id if accepted else None,
        )

    async def enqueue_updates(
        self,
        updates: Sequence[dict[str, Any]],
    ) -> list[WebhookEnqueueResult | Exception]:
        results: list[WebhookEnqueueResult | Exception | None] = [None] * len(updates)
        prepared: list[tuple[int, _PreparedWebhookUpdate]] = []
        for index, update in enumerate(updates):
            try:
                prepared.append((index, _prepare_update(update, dedupe_key_prefix=self._dedupe_key_prefix)))
            except InvalidWebhookUpdateError as exc:
                results[index] = exc

        if prepared:
            try:
                redis_results = await self._enqueue_many_evalsha([item for _index, item in prepared])
            except RedisError as exc:
                raise WebhookIngressQueueError("webhook_ingress_enqueue_unavailable") from exc
            for (index, item), redis_result in zip(prepared, redis_results):
                accepted, stream_id = _parse_enqueue_result(redis_result)
                results[index] = WebhookEnqueueResult(
                    accepted=accepted,
                    duplicate=not accepted,
                    update_id=item.update_id,
                    stream_id=stream_id if accepted else None,
                )

        return [
            result if result is not None else WebhookIngressQueueError("webhook_ingress_enqueue_missing")
            for result in results
        ]

    async def read_batch(
        self,
        *,
        consumer_name: str,
        count: int,
        block_ms: int,
    ) -> list[WebhookStreamMessage]:
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
            raise WebhookIngressQueueError("webhook_ingress_read_unavailable") from exc
        return _parse_stream_batches(batches)

    async def claim_stale(
        self,
        *,
        consumer_name: str,
        min_idle_ms: int,
        count: int,
    ) -> list[WebhookStreamMessage]:
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
            raise WebhookIngressQueueError("webhook_ingress_claim_unavailable") from exc
        return _parse_xautoclaim_result(result)

    async def mark_processed(self, message: WebhookStreamMessage) -> None:
        await self.mark_processed_many([message])

    async def mark_processed_many(
        self,
        messages: list[WebhookStreamMessage],
        *,
        dispatch_durations_ms: list[float] | None = None,
    ) -> None:
        if not messages:
            return
        message_ids = [message.message_id for message in messages]
        now_ms = await _redis_now_ms(self._redis)
        pipe = self._redis.pipeline()
        pipe.xack(self._stream_key, self._group_name, *message_ids)
        pipe.xdel(self._stream_key, *message_ids)
        pipe.incrby(_metric_key(self._metrics_key_prefix, "processed_total"), len(messages))
        for message in messages:
            pipe.lpush(_metric_key(self._metrics_key_prefix, "processing_lag_ms"), str(max(0, now_ms - message.enqueued_at_ms)))
        for duration_ms in dispatch_durations_ms or []:
            pipe.lpush(_metric_key(self._metrics_key_prefix, "worker_dispatch_ms"), str(max(0.0, duration_ms)))
        pipe.ltrim(_metric_key(self._metrics_key_prefix, "processing_lag_ms"), 0, self._processing_lag_sample_size - 1)
        pipe.ltrim(_metric_key(self._metrics_key_prefix, "worker_dispatch_ms"), 0, self._processing_lag_sample_size - 1)
        await pipe.execute()

    async def retry_or_dead(
        self,
        message: WebhookStreamMessage,
        *,
        max_attempts: int,
        error_message: str,
    ) -> bool:
        next_attempt = message.attempt + 1
        if next_attempt >= max(1, max_attempts):
            await _dead_letter(
                self._redis,
                stream_key=self._stream_key,
                group_name=self._group_name,
                dead_letter_key=self._dead_letter_key,
                message=message,
                error_message=error_message,
                attempts=next_attempt,
            )
            await self._redis.incr(_metric_key(self._metrics_key_prefix, "dead_total"))
            return False

        await _retry(
            self._redis,
            stream_key=self._stream_key,
            group_name=self._group_name,
            message=message,
            error_message=error_message,
            attempt=next_attempt,
        )
        await self._redis.incr(_metric_key(self._metrics_key_prefix, "failed_total"))
        return True

    async def stats(self) -> WebhookIngressQueueStats:
        try:
            stream_length = int(await self._redis.xlen(self._stream_key))
            dead_letter_length = int(await self._redis.xlen(self._dead_letter_key))
            pending, lag = await _group_pending_and_lag(self._redis, self._stream_key, self._group_name)
            oldest_lag_ms = await _oldest_lag_ms(self._redis, self._stream_key)
            processed_total = await _metric_int(self._redis, self._metrics_key_prefix, "processed_total")
            failed_total = await _metric_int(self._redis, self._metrics_key_prefix, "failed_total")
            dead_total = await _metric_int(self._redis, self._metrics_key_prefix, "dead_total")
        except RedisError as exc:
            raise WebhookIngressQueueError("webhook_ingress_stats_unavailable") from exc
        return WebhookIngressQueueStats(
            stream_length=stream_length,
            dead_letter_length=dead_letter_length,
            pending=pending,
            lag=lag,
            oldest_lag_ms=oldest_lag_ms,
            processed_total=processed_total,
            failed_total=failed_total,
            dead_total=dead_total,
        )

    async def processing_lag_samples(self, *, limit: int = 10_000) -> list[float]:
        try:
            raw_values = await self._redis.lrange(
                _metric_key(self._metrics_key_prefix, "processing_lag_ms"),
                0,
                max(0, limit - 1),
            )
        except RedisError as exc:
            raise WebhookIngressQueueError("webhook_ingress_lag_samples_unavailable") from exc
        return [_float_value(value) for value in raw_values]

    async def worker_dispatch_samples(self, *, limit: int = 10_000) -> list[float]:
        try:
            raw_values = await self._redis.lrange(
                _metric_key(self._metrics_key_prefix, "worker_dispatch_ms"),
                0,
                max(0, limit - 1),
            )
        except RedisError as exc:
            raise WebhookIngressQueueError("webhook_ingress_dispatch_samples_unavailable") from exc
        return [_float_value(value) for value in raw_values]

    async def _enqueue_evalsha(self, *args: object) -> object:
        script_sha = await self._enqueue_script_sha_value()
        try:
            return await self._redis.evalsha(script_sha, 2, *args)
        except NoScriptError:
            self._enqueue_script_sha = None
            script_sha = await self._enqueue_script_sha_value()
            return await self._redis.evalsha(script_sha, 2, *args)

    async def _enqueue_many_evalsha(self, updates: Sequence[_PreparedWebhookUpdate]) -> list[object]:
        script_sha = await self._enqueue_batch_script_sha_value()
        try:
            return await self._execute_enqueue_batch_script(script_sha, updates)
        except NoScriptError:
            self._enqueue_batch_script_sha = None
            script_sha = await self._enqueue_batch_script_sha_value()
            return await self._execute_enqueue_batch_script(script_sha, updates)

    async def _execute_enqueue_batch_script(
        self,
        script_sha: str,
        updates: Sequence[_PreparedWebhookUpdate],
    ) -> list[object]:
        args: list[object] = [self._dedupe_ttl_seconds, "0"]
        for item in updates:
            args.extend([item.dedupe_key, item.payload, str(item.update_id)])
        return list(await self._redis.evalsha(script_sha, 1, self._stream_key, *args))

    async def _enqueue_script_sha_value(self) -> str:
        if self._enqueue_script_sha is not None:
            return self._enqueue_script_sha
        async with self._enqueue_script_lock:
            if self._enqueue_script_sha is None:
                self._enqueue_script_sha = str(await self._redis.script_load(ENQUEUE_UPDATE_SCRIPT))
            return self._enqueue_script_sha

    async def _enqueue_batch_script_sha_value(self) -> str:
        if self._enqueue_batch_script_sha is not None:
            return self._enqueue_batch_script_sha
        async with self._enqueue_script_lock:
            if self._enqueue_batch_script_sha is None:
                self._enqueue_batch_script_sha = str(await self._redis.script_load(ENQUEUE_UPDATE_BATCH_SCRIPT))
            return self._enqueue_batch_script_sha


def _prepare_update(update: dict[str, Any], *, dedupe_key_prefix: str) -> _PreparedWebhookUpdate:
    update_id = _extract_update_id(update)
    return _PreparedWebhookUpdate(
        update_id=update_id,
        dedupe_key=f"{dedupe_key_prefix}:{update_id}",
        payload=_encode_payload(update),
    )


async def _retry(
    redis_client: Redis,
    *,
    stream_key: str,
    group_name: str,
    message: WebhookStreamMessage,
    error_message: str,
    attempt: int,
) -> None:
    await redis_client.xadd(
        stream_key,
        {
            "payload": _encode_payload(message.payload),
            "update_id": str(message.update_id),
            "enqueued_at_ms": str(message.enqueued_at_ms),
            "attempt": str(attempt),
            "last_error": error_message[:500],
            "original_message_id": message.message_id,
        },
    )
    await _ack_delete(redis_client, stream_key=stream_key, group_name=group_name, message_id=message.message_id)


async def _dead_letter(
    redis_client: Redis,
    *,
    stream_key: str,
    group_name: str,
    dead_letter_key: str,
    message: WebhookStreamMessage,
    error_message: str,
    attempts: int,
) -> None:
    await redis_client.xadd(
        dead_letter_key,
        {
            "payload": _encode_payload(message.payload),
            "update_id": str(message.update_id),
            "enqueued_at_ms": str(message.enqueued_at_ms),
            "attempt": str(attempts),
            "failed_at_ms": str(_now_ms()),
            "error": error_message[:1000],
            "original_message_id": message.message_id,
        },
    )
    await _ack_delete(redis_client, stream_key=stream_key, group_name=group_name, message_id=message.message_id)


async def _ack_delete(redis_client: Redis, *, stream_key: str, group_name: str, message_id: str) -> None:
    await redis_client.xack(stream_key, group_name, message_id)
    await redis_client.xdel(stream_key, message_id)


async def _group_pending_and_lag(redis_client: Redis, stream_key: str, group_name: str) -> tuple[int, int | None]:
    try:
        groups = await redis_client.xinfo_groups(stream_key)
    except RedisError as exc:
        if "no such key" in str(exc).lower():
            return 0, 0
        raise
    for group in groups:
        if str(group.get("name")) == group_name:
            pending = _int_value(group.get("pending"))
            lag_raw = group.get("lag")
            return pending, None if lag_raw is None else _int_value(lag_raw)
    return 0, 0


async def _oldest_lag_ms(redis_client: Redis, stream_key: str) -> int:
    rows = await redis_client.xrange(stream_key, count=1)
    if not rows:
        return 0
    _, fields = rows[0]
    enqueued_at_ms = _int_value(fields.get("enqueued_at_ms"))
    return max(0, _now_ms() - enqueued_at_ms)


async def _metric_int(redis_client: Redis, metrics_key_prefix: str, name: str) -> int:
    value = await redis_client.get(_metric_key(metrics_key_prefix, name))
    return _int_value(value)


def _metric_key(metrics_key_prefix: str, name: str) -> str:
    return f"{metrics_key_prefix}:{name}"


def _extract_update_id(update: dict[str, Any]) -> int:
    update_id = update.get("update_id")
    if not isinstance(update_id, int):
        raise InvalidWebhookUpdateError("telegram update_id must be an integer")
    return update_id


def _encode_payload(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _decode_payload(raw_payload: object) -> dict[str, Any]:
    if not isinstance(raw_payload, str):
        raise WebhookIngressQueueError("webhook_ingress_payload_invalid")
    payload = json.loads(raw_payload)
    if not isinstance(payload, dict):
        raise WebhookIngressQueueError("webhook_ingress_payload_invalid")
    return payload


def _now_ms() -> int:
    return int(time() * 1000)


async def _redis_now_ms(redis_client: Redis) -> int:
    seconds, microseconds = await redis_client.time()
    return (int(seconds) * 1000) + (int(microseconds) // 1000)


def _parse_enqueue_result(result: object) -> tuple[bool, str | None]:
    if not isinstance(result, (list, tuple)) or len(result) != 2:
        raise WebhookIngressQueueError("webhook_ingress_enqueue_result_invalid")
    accepted = bool(int(result[0]))
    stream_id = str(result[1]) if result[1] else None
    return accepted, stream_id


def _parse_stream_batches(batches: object) -> list[WebhookStreamMessage]:
    messages: list[WebhookStreamMessage] = []
    if not isinstance(batches, list):
        return messages
    for _, rows in batches:
        for message_id, fields in rows:
            messages.append(_stream_message(str(message_id), fields))
    return messages


def _parse_xautoclaim_result(result: object) -> list[WebhookStreamMessage]:
    if not isinstance(result, (list, tuple)) or len(result) < 2:
        return []
    rows = result[1]
    return [_stream_message(str(message_id), fields) for message_id, fields in rows]


def _stream_message(message_id: str, fields: dict[str, object]) -> WebhookStreamMessage:
    payload = _decode_payload(fields.get("payload"))
    update_id = _int_value(fields.get("update_id"))
    return WebhookStreamMessage(
        message_id=message_id,
        update_id=update_id,
        payload=payload,
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


def _float_value(value: object) -> float:
    if value is None:
        return 0.0
    return float(value)
