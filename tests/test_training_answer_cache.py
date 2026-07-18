from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from redis.exceptions import RedisError

from app.services import training_answer_cache
from tests.test_answer_write_behind_pipeline import _pending_payload


@pytest.mark.asyncio
async def test_cache_disabled_does_not_touch_redis(monkeypatch) -> None:
    redis_factory = _RedisFactory()
    monkeypatch.setattr(
        training_answer_cache,
        "get_settings",
        lambda: _settings(enabled=False),
    )
    monkeypatch.setattr(
        training_answer_cache,
        "get_or_create_shared_redis_client",
        redis_factory,
    )

    payload = _pending_payload()
    await training_answer_cache.cache_pending_question_if_enabled(payload)
    cached = await training_answer_cache.get_cached_pending_question_if_enabled(
        session_id=payload.session_id,
        question_token=payload.question_token,
    )
    await training_answer_cache.delete_cached_pending_question_if_enabled(
        session_id=payload.session_id,
        question_token=payload.question_token,
    )

    assert cached is None
    assert redis_factory.calls == 0


@pytest.mark.asyncio
async def test_cache_round_trip_uses_stable_key_and_ttl(monkeypatch) -> None:
    redis_client = _RedisStub()
    monkeypatch.setattr(training_answer_cache, "get_settings", lambda: _settings(enabled=True, ttl=77))
    monkeypatch.setattr(
        training_answer_cache,
        "get_or_create_shared_redis_client",
        lambda _settings: redis_client,
    )
    payload = _pending_payload()

    await training_answer_cache.cache_pending_question_if_enabled(payload)
    cached = await training_answer_cache.get_cached_pending_question_if_enabled(
        session_id=payload.session_id,
        question_token=payload.question_token,
    )
    await training_answer_cache.delete_cached_pending_question_if_enabled(
        session_id=payload.session_id,
        question_token=payload.question_token,
    )

    key = "dtb:training:pending_question:1:tok1"
    assert redis_client.set_calls == [(key, 77)]
    assert cached == payload
    assert redis_client.deleted == [key]


@pytest.mark.asyncio
async def test_cache_read_failure_returns_placeholders(monkeypatch) -> None:
    redis_client = _RedisStub(read_error=RedisError("down"))
    monkeypatch.setattr(training_answer_cache, "get_settings", lambda: _settings(enabled=True))
    monkeypatch.setattr(
        training_answer_cache,
        "get_or_create_shared_redis_client",
        lambda _settings: redis_client,
    )

    cached = await training_answer_cache.get_cached_pending_questions_if_enabled(
        [(1, "tok1"), (2, "tok2")]
    )

    assert cached == [None, None]


def test_decode_pending_payload_rejects_invalid_json_and_non_objects() -> None:
    assert training_answer_cache._decode_pending_payload(b"{bad-json") is None
    assert training_answer_cache._decode_pending_payload(json.dumps(["not", "object"])) is None
    assert training_answer_cache._decode_pending_payload(None) is None


def test_pending_question_key_is_namespaced_by_session_and_token() -> None:
    assert (
        training_answer_cache._pending_question_key(42, "question-token")
        == "dtb:training:pending_question:42:question-token"
    )


class _RedisFactory:
    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, _settings):
        self.calls += 1
        raise AssertionError("cache is disabled")


class _RedisStub:
    def __init__(self, *, read_error: Exception | None = None) -> None:
        self._store: dict[str, str] = {}
        self._read_error = read_error
        self.set_calls: list[tuple[str, int]] = []
        self.deleted: list[str] = []

    async def set(self, key: str, value: str, *, ex: int) -> None:
        self._store[key] = value
        self.set_calls.append((key, ex))

    async def mget(self, keys: list[str]) -> list[str | None]:
        if self._read_error is not None:
            raise self._read_error
        return [self._store.get(key) for key in keys]

    async def delete(self, key: str) -> None:
        self.deleted.append(key)
        self._store.pop(key, None)


def _settings(*, enabled: bool, ttl: int = 60):
    return SimpleNamespace(
        training_answer_cache_enabled=enabled,
        training_answer_cache_ttl_seconds=ttl,
    )
