from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
import logging
from time import monotonic
from uuid import uuid4

from redis.exceptions import RedisError

from app.config import AppEnvironment, get_settings
from app.runtime.redis import get_or_create_shared_redis_client

logger = logging.getLogger(__name__)

REDIS_LOCK_PREFIX = "dtb:answer_attempt_lock"
REDIS_LOCK_TTL_SECONDS = 30
REDIS_LOCK_WAIT_TIMEOUT_SECONDS = 30.0
REDIS_LOCK_POLL_INTERVAL_SECONDS = 0.01
REDIS_LOCK_RELEASE_SCRIPT = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
  return redis.call('DEL', KEYS[1])
end
return 0
"""


@dataclass
class _LockEntry:
    lock: asyncio.Lock
    refcount: int = 0


_registry_guard = asyncio.Lock()
_locks: dict[str, _LockEntry] = {}


class IdempotencyLockBackendError(RuntimeError):
    """Raised when the shared answer idempotency lock cannot coordinate safely."""


@asynccontextmanager
async def answer_attempt_lock(key: str) -> AsyncIterator[None]:
    if _uses_redis_answer_lock():
        async with _redis_answer_attempt_lock(key):
            yield
        return

    async with _local_answer_attempt_lock(key):
        yield


@asynccontextmanager
async def _local_answer_attempt_lock(key: str) -> AsyncIterator[None]:
    async with _registry_guard:
        entry = _locks.get(key)
        if entry is None:
            entry = _LockEntry(asyncio.Lock())
            _locks[key] = entry
        entry.refcount += 1

    await entry.lock.acquire()
    try:
        yield
    finally:
        entry.lock.release()
        async with _registry_guard:
            entry.refcount -= 1
            if entry.refcount <= 0 and not entry.lock.locked():
                _locks.pop(key, None)


@asynccontextmanager
async def _redis_answer_attempt_lock(key: str) -> AsyncIterator[None]:
    settings = get_settings()
    redis_client = get_or_create_shared_redis_client(settings)
    token = uuid4().hex
    redis_key = f"{REDIS_LOCK_PREFIX}:{key}"
    deadline = monotonic() + REDIS_LOCK_WAIT_TIMEOUT_SECONDS

    while True:
        try:
            acquired = await redis_client.set(redis_key, token, ex=REDIS_LOCK_TTL_SECONDS, nx=True)
        except RedisError as exc:
            raise IdempotencyLockBackendError("redis_answer_lock_unavailable") from exc
        if acquired:
            break
        if monotonic() >= deadline:
            raise IdempotencyLockBackendError("redis_answer_lock_timeout")
        await asyncio.sleep(REDIS_LOCK_POLL_INTERVAL_SECONDS)

    try:
        yield
    finally:
        try:
            await redis_client.eval(REDIS_LOCK_RELEASE_SCRIPT, 1, redis_key, token)
        except RedisError as exc:
            logger.warning("answer idempotency lock release failed: %s", exc.__class__.__name__)


def _uses_redis_answer_lock() -> bool:
    settings = get_settings()
    if settings.security_state_backend == "redis":
        return True
    if settings.security_state_backend == "in_memory":
        return False
    return settings.app_env != AppEnvironment.development
