"""Shared admission control for Telegram update handling."""

from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from math import ceil
from uuid import uuid4

from redis.asyncio import Redis
from redis.exceptions import RedisError

logger = logging.getLogger(__name__)

REDIS_ADMISSION_ACQUIRE_SCRIPT = """
local key = KEYS[1]
local limit = tonumber(ARGV[1])
local lease_ms = tonumber(ARGV[2])
local ttl_seconds = tonumber(ARGV[3])
local token = ARGV[4]

local now = redis.call('TIME')
local now_ms = (tonumber(now[1]) * 1000) + math.floor(tonumber(now[2]) / 1000)

redis.call('ZREMRANGEBYSCORE', key, '-inf', now_ms)
local count = redis.call('ZCARD', key)
if count >= limit then
  return {0, count}
end

redis.call('ZADD', key, now_ms + lease_ms, token)
redis.call('EXPIRE', key, ttl_seconds)
return {1, count + 1}
"""

REDIS_ADMISSION_RENEW_SCRIPT = """
local key = KEYS[1]
local token = ARGV[1]
local lease_ms = tonumber(ARGV[2])
local ttl_seconds = tonumber(ARGV[3])

if redis.call('ZSCORE', key, token) == false then
  return 0
end

local now = redis.call('TIME')
local now_ms = (tonumber(now[1]) * 1000) + math.floor(tonumber(now[2]) / 1000)

redis.call('ZADD', key, now_ms + lease_ms, token)
redis.call('EXPIRE', key, ttl_seconds)
return 1
"""

REDIS_ADMISSION_RELEASE_SCRIPT = """
local key = KEYS[1]
local token = ARGV[1]

local removed = redis.call('ZREM', key, token)
if redis.call('ZCARD', key) == 0 then
  redis.call('DEL', key)
end
return removed
"""


class AdmissionBackendError(RuntimeError):
    """Raised when the shared admission backend cannot coordinate safely."""


class AdmissionLease:
    async def release(self) -> None:
        raise NotImplementedError


class AdmissionController:
    def __init__(self, *, limit: int) -> None:
        self.limit = max(1, limit)

    @property
    def is_shared(self) -> bool:
        return False

    async def try_acquire(self, *, timeout_seconds: float) -> AdmissionLease | None:
        raise NotImplementedError


class LocalAdmissionLease(AdmissionLease):
    def __init__(self, semaphore: asyncio.Semaphore) -> None:
        self._semaphore = semaphore
        self._released = False

    async def release(self) -> None:
        if self._released:
            return
        self._released = True
        self._semaphore.release()


class LocalAdmissionController(AdmissionController):
    def __init__(self, *, limit: int) -> None:
        super().__init__(limit=limit)
        self._semaphore = asyncio.Semaphore(self.limit)

    @property
    def semaphore(self) -> asyncio.Semaphore:
        return self._semaphore

    async def try_acquire(self, *, timeout_seconds: float) -> AdmissionLease | None:
        timeout_seconds = max(0.0, timeout_seconds)
        if timeout_seconds == 0:
            if getattr(self._semaphore, "_value", 0) <= 0:
                return None
            await self._semaphore.acquire()
            return LocalAdmissionLease(self._semaphore)

        try:
            await asyncio.wait_for(self._semaphore.acquire(), timeout_seconds)
        except TimeoutError:
            return None
        return LocalAdmissionLease(self._semaphore)


class RedisAdmissionController(AdmissionController):
    def __init__(
        self,
        redis_client: Redis,
        *,
        limit: int,
        key: str = "dtb:admission:global_in_flight",
        lease_ttl_seconds: int = 120,
    ) -> None:
        super().__init__(limit=limit)
        self._redis = redis_client
        self._key = key
        self._lease_ttl_seconds = max(5, lease_ttl_seconds)
        self._lease_ttl_milliseconds = self._lease_ttl_seconds * 1000
        self._key_ttl_seconds = self._lease_ttl_seconds + max(1, ceil(self._lease_ttl_seconds / 10))

    @property
    def is_shared(self) -> bool:
        return True

    async def try_acquire(self, *, timeout_seconds: float) -> AdmissionLease | None:
        lease = await self._try_acquire_once()
        if lease is not None or timeout_seconds <= 0:
            return lease
        await asyncio.sleep(max(0.0, timeout_seconds))
        return await self._try_acquire_once()

    async def _try_acquire_once(self) -> AdmissionLease | None:
        token = uuid4().hex
        try:
            result = await self._redis.eval(
                REDIS_ADMISSION_ACQUIRE_SCRIPT,
                1,
                self._key,
                self.limit,
                self._lease_ttl_milliseconds,
                self._key_ttl_seconds,
                token,
            )
        except RedisError as exc:
            raise AdmissionBackendError("redis_admission_unavailable") from exc

        if not _parse_redis_flag(result):
            return None
        return RedisAdmissionLease(
            self._redis,
            key=self._key,
            token=token,
            lease_ttl_seconds=self._lease_ttl_seconds,
            key_ttl_seconds=self._key_ttl_seconds,
        )


class RedisAdmissionLease(AdmissionLease):
    def __init__(
        self,
        redis_client: Redis,
        *,
        key: str,
        token: str,
        lease_ttl_seconds: int,
        key_ttl_seconds: int,
    ) -> None:
        self._redis = redis_client
        self._key = key
        self._token = token
        self._lease_ttl_seconds = lease_ttl_seconds
        self._lease_ttl_milliseconds = lease_ttl_seconds * 1000
        self._key_ttl_seconds = key_ttl_seconds
        self._released = False
        self._renew_task = asyncio.create_task(self._renew_loop())

    async def release(self) -> None:
        if self._released:
            return
        self._released = True
        self._renew_task.cancel()
        with suppress(asyncio.CancelledError):
            await self._renew_task

        try:
            await self._redis.eval(
                REDIS_ADMISSION_RELEASE_SCRIPT,
                1,
                self._key,
                self._token,
            )
        except RedisError as exc:
            logger.warning("shared admission release failed: %s", exc.__class__.__name__)

    async def _renew_loop(self) -> None:
        interval_seconds = max(1.0, self._lease_ttl_seconds / 3)
        while True:
            await asyncio.sleep(interval_seconds)
            try:
                renewed = await self._redis.eval(
                    REDIS_ADMISSION_RENEW_SCRIPT,
                    1,
                    self._key,
                    self._token,
                    self._lease_ttl_milliseconds,
                    self._key_ttl_seconds,
                )
            except RedisError as exc:
                logger.warning("shared admission renewal failed: %s", exc.__class__.__name__)
                continue
            if not _parse_redis_flag(renewed):
                return


def _parse_redis_flag(result: object) -> bool:
    raw_value = result
    if isinstance(result, (list, tuple)):
        if not result:
            raise AdmissionBackendError("invalid_redis_admission_result")
        raw_value = result[0]
    try:
        return bool(int(raw_value))
    except (TypeError, ValueError) as exc:
        raise AdmissionBackendError("invalid_redis_admission_result") from exc


__all__ = [
    "AdmissionBackendError",
    "AdmissionController",
    "AdmissionLease",
    "LocalAdmissionController",
    "RedisAdmissionController",
]
