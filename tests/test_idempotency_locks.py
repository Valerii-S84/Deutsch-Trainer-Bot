from __future__ import annotations

import asyncio

import pytest

import app.runtime.idempotency_locks as idempotency_locks
from app.config import Settings


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    async def set(self, key: str, value: str, *, ex: int, nx: bool):
        del ex
        if nx and key in self.values:
            return None
        self.values[key] = value
        return True

    async def eval(self, _script, _numkeys, key: str, token: str) -> int:
        if self.values.get(key) != token:
            return 0
        self.values.pop(key, None)
        return 1


@pytest.mark.asyncio
async def test_answer_attempt_lock_uses_shared_redis_to_serialize_across_replicas(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redis = FakeRedis()
    settings = Settings(SECURITY_STATE_BACKEND="redis", REDIS_URL="redis://cache:6379/0")
    monkeypatch.setattr(idempotency_locks, "get_settings", lambda: settings)
    monkeypatch.setattr(idempotency_locks, "get_or_create_shared_redis_client", lambda _settings: redis)

    entered: list[str] = []
    first_entered = asyncio.Event()
    first_release = asyncio.Event()
    second_entered = asyncio.Event()

    async def first_replica() -> None:
        async with idempotency_locks.answer_attempt_lock("session:question"):
            entered.append("first")
            first_entered.set()
            await first_release.wait()

    async def second_replica() -> None:
        await first_entered.wait()
        async with idempotency_locks.answer_attempt_lock("session:question"):
            entered.append("second")
            second_entered.set()

    first_task = asyncio.create_task(first_replica())
    second_task = asyncio.create_task(second_replica())

    await first_entered.wait()
    await asyncio.sleep(0.05)
    assert second_entered.is_set() is False

    first_release.set()
    await asyncio.gather(first_task, second_task)

    assert entered == ["first", "second"]
