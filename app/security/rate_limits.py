from __future__ import annotations

from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from time import monotonic


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


def _drop_expired(bucket: deque[float], *, now: float, window_seconds: int) -> None:
    while bucket and now - bucket[0] >= window_seconds:
        bucket.popleft()
