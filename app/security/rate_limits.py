from __future__ import annotations

from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from time import monotonic
from uuid import uuid4

from redis.exceptions import RedisError


ACTION_ADMIN = "admin"
ACTION_ANSWER = "answer"
ACTION_PAYMENT_START = "payment_start"
ACTION_PAYWALL_CLICK = "paywall_click"
ACTION_RETRY = "retry"
ACTION_START = "start"
ACTION_TRAINING_START = "training_start"


@dataclass(frozen=True)
class RateLimitRule:
    action: str
    limit: int
    window_seconds: int


@dataclass(frozen=True)
class RateLimitDecision:
    action: str
    allowed: bool
    retry_after_seconds: int


DEFAULT_RATE_LIMIT_RULES = {
    ACTION_START: RateLimitRule(ACTION_START, limit=5, window_seconds=60),
    ACTION_TRAINING_START: RateLimitRule(ACTION_TRAINING_START, limit=8, window_seconds=60),
    ACTION_ANSWER: RateLimitRule(ACTION_ANSWER, limit=20, window_seconds=10),
    ACTION_RETRY: RateLimitRule(ACTION_RETRY, limit=10, window_seconds=60),
    ACTION_PAYWALL_CLICK: RateLimitRule(ACTION_PAYWALL_CLICK, limit=10, window_seconds=60),
    ACTION_PAYMENT_START: RateLimitRule(ACTION_PAYMENT_START, limit=4, window_seconds=60),
    ACTION_ADMIN: RateLimitRule(ACTION_ADMIN, limit=3, window_seconds=60),
}

REDIS_RATE_LIMIT_SCRIPT = """
local key = KEYS[1]
local now_ms = tonumber(ARGV[1])
local window_ms = tonumber(ARGV[2])
local limit = tonumber(ARGV[3])
local ttl_seconds = tonumber(ARGV[4])
local member = ARGV[5]
local oldest_allowed = now_ms - window_ms

redis.call('ZREMRANGEBYSCORE', key, 0, oldest_allowed)
local count = redis.call('ZCARD', key)
if count >= limit then
  local oldest = redis.call('ZRANGE', key, 0, 0, 'WITHSCORES')
  local retry_ms = window_ms
  if oldest[2] ~= nil then
    retry_ms = window_ms - (now_ms - tonumber(oldest[2]))
  end
  if retry_ms < 1000 then
    retry_ms = 1000
  end
  return {0, math.ceil(retry_ms / 1000)}
end

redis.call('ZADD', key, now_ms, member)
redis.call('EXPIRE', key, ttl_seconds)
return {1, 0}
"""


class RateLimitBackendError(Exception):
    """Raised when the global security state backend is unavailable."""


class InMemoryRateLimiter:
    """Small action/user sliding-window limiter for single-process bot runtime."""

    def __init__(
        self,
        rules: dict[str, RateLimitRule] | None = None,
        *,
        time_func: Callable[[], float] = monotonic,
    ) -> None:
        self._rules = rules or DEFAULT_RATE_LIMIT_RULES
        self._time_func = time_func
        self._hits: dict[tuple[str, str], deque[float]] = {}

    def check(self, *, action: str, identity: str) -> RateLimitDecision:
        rule = self._rules.get(action)
        if rule is None:
            return RateLimitDecision(action=action, allowed=True, retry_after_seconds=0)

        now = self._time_func()
        bucket = self._hits.setdefault((action, identity), deque())
        _drop_expired(bucket, now=now, window_seconds=rule.window_seconds)
        if len(bucket) >= rule.limit:
            retry_after = max(1, round(rule.window_seconds - (now - bucket[0])))
            return RateLimitDecision(action=action, allowed=False, retry_after_seconds=retry_after)

        bucket.append(now)
        return RateLimitDecision(action=action, allowed=True, retry_after_seconds=0)


class RedisRateLimiter:
    """Redis-backed sliding-window limiter for multi-process production runtime."""

    def __init__(
        self,
        redis_client,
        rules: dict[str, RateLimitRule] | None = None,
        *,
        key_prefix: str = "dtb:rate_limit",
        time_func: Callable[[], float] | None = None,
    ) -> None:
        self._redis = redis_client
        self._rules = rules or DEFAULT_RATE_LIMIT_RULES
        self._key_prefix = key_prefix
        self._time_func = time_func

    async def check(self, *, action: str, identity: str) -> RateLimitDecision:
        rule = self._rules.get(action)
        if rule is None:
            return RateLimitDecision(action=action, allowed=True, retry_after_seconds=0)

        key = f"{self._key_prefix}:{action}:{identity}"
        now_ms = await self._now_ms()
        window_ms = rule.window_seconds * 1000
        member = f"{now_ms}:{uuid4().hex}"
        try:
            result = await self._redis.eval(
                REDIS_RATE_LIMIT_SCRIPT,
                1,
                key,
                now_ms,
                window_ms,
                rule.limit,
                rule.window_seconds + 1,
                member,
            )
        except RedisError as exc:
            raise RateLimitBackendError("redis_rate_limiter_unavailable") from exc

        allowed, retry_after = _parse_redis_rate_limit_result(result)
        return RateLimitDecision(
            action=action,
            allowed=allowed,
            retry_after_seconds=retry_after,
        )

    async def _now_ms(self) -> int:
        if self._time_func is not None:
            return int(self._time_func() * 1000)
        try:
            seconds, microseconds = await self._redis.time()
        except RedisError as exc:
            raise RateLimitBackendError("redis_time_unavailable") from exc
        return int(seconds) * 1000 + int(microseconds) // 1000


class DuplicateUpdateGuard:
    """Remember processed Telegram update ids for a bounded TTL."""

    def __init__(self, *, ttl_seconds: int = 300, time_func: Callable[[], float] = monotonic) -> None:
        self._ttl_seconds = max(1, ttl_seconds)
        self._time_func = time_func
        self._seen_until: dict[int, float] = {}

    def accept(self, update_id: int | None) -> bool:
        if update_id is None:
            return True

        now = self._time_func()
        self._drop_expired(now)
        if update_id in self._seen_until:
            return False

        self._seen_until[update_id] = now + self._ttl_seconds
        return True

    def _drop_expired(self, now: float) -> None:
        expired = [update_id for update_id, expires_at in self._seen_until.items() if expires_at <= now]
        for update_id in expired:
            self._seen_until.pop(update_id, None)


class RedisDuplicateUpdateGuard:
    """Redis-backed Telegram update id guard for multi-process webhook runtime."""

    def __init__(
        self,
        redis_client,
        *,
        ttl_seconds: int = 300,
        key_prefix: str = "dtb:telegram_update",
    ) -> None:
        self._redis = redis_client
        self._ttl_seconds = max(1, ttl_seconds)
        self._key_prefix = key_prefix

    async def accept(self, update_id: int | None) -> bool:
        if update_id is None:
            return True
        key = f"{self._key_prefix}:{update_id}"
        try:
            created = await self._redis.set(key, "1", ex=self._ttl_seconds, nx=True)
        except RedisError as exc:
            raise RateLimitBackendError("redis_duplicate_guard_unavailable") from exc
        return bool(created)


def _drop_expired(bucket: deque[float], *, now: float, window_seconds: int) -> None:
    while bucket and now - bucket[0] >= window_seconds:
        bucket.popleft()


def _parse_redis_rate_limit_result(result: object) -> tuple[bool, int]:
    if not isinstance(result, (list, tuple)) or len(result) != 2:
        raise RateLimitBackendError("invalid_redis_rate_limit_result")
    allowed_raw, retry_raw = result
    return bool(int(allowed_raw)), max(0, int(retry_raw))
