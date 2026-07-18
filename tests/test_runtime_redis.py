from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from redis.exceptions import RedisError

from app.config import Settings
from app.runtime.admission import AdmissionBackendError, RedisAdmissionController
from app.runtime import redis as redis_runtime


def test_create_redis_client_registers_shared_client(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_client = SimpleNamespace(aclose=AsyncMock())

    def fake_from_url(url: str, *, decode_responses: bool, max_connections: int):
        assert url == "redis://cache.example.test:6379/0"
        assert decode_responses is True
        assert max_connections == 64
        return fake_client

    monkeypatch.setattr(redis_runtime, "_shared_redis_client", None)
    monkeypatch.setattr(redis_runtime.Redis, "from_url", fake_from_url)

    client = redis_runtime.create_redis_client(
        Settings(redis_url="redis://cache.example.test:6379/0", REDIS_MAX_CONNECTIONS=64),
    )

    assert client is fake_client
    assert redis_runtime.get_shared_redis_client() is fake_client


def test_get_or_create_shared_redis_client_reuses_existing_client(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_client = SimpleNamespace(aclose=AsyncMock())
    monkeypatch.setattr(redis_runtime, "_shared_redis_client", fake_client)

    client = redis_runtime.get_or_create_shared_redis_client(Settings())

    assert client is fake_client


def test_create_redis_client_reuses_registered_shared_client(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_client = SimpleNamespace(aclose=AsyncMock())
    monkeypatch.setattr(redis_runtime, "_shared_redis_client", fake_client)
    from_url = AsyncMock()
    monkeypatch.setattr(redis_runtime.Redis, "from_url", from_url)

    client = redis_runtime.create_redis_client(Settings())

    assert client is fake_client
    from_url.assert_not_called()


@pytest.mark.asyncio
async def test_warm_redis_client_pings_requested_connection_count() -> None:
    fake_client = SimpleNamespace(ping=AsyncMock(return_value=True))

    result = await redis_runtime.warm_redis_client(fake_client, connection_count=4)

    assert result == {"requested": 4, "succeeded": 4, "failed": 0}
    assert fake_client.ping.await_count == 4


@pytest.mark.asyncio
async def test_redis_admission_controller_acquires_and_releases_lease() -> None:
    redis_client = SimpleNamespace(eval=AsyncMock(side_effect=[[1, 1], 1]))
    controller = RedisAdmissionController(redis_client, limit=2, lease_ttl_seconds=30)

    lease = await controller.try_acquire(timeout_seconds=0)

    assert lease is not None
    assert controller.is_shared is True
    await lease.release()
    assert redis_client.eval.await_count == 2


@pytest.mark.asyncio
async def test_redis_admission_controller_raises_on_backend_error() -> None:
    redis_client = SimpleNamespace(eval=AsyncMock(side_effect=RedisError("down")))
    controller = RedisAdmissionController(redis_client, limit=2, lease_ttl_seconds=30)

    with pytest.raises(AdmissionBackendError):
        await controller.try_acquire(timeout_seconds=0)


@pytest.mark.asyncio
async def test_close_redis_client_clears_shared_client(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_client = SimpleNamespace(aclose=AsyncMock())
    monkeypatch.setattr(redis_runtime, "_shared_redis_client", fake_client)

    await redis_runtime.close_redis_client(fake_client)

    fake_client.aclose.assert_awaited_once()
    assert redis_runtime.get_shared_redis_client() is None


@pytest.mark.asyncio
async def test_close_redis_client_closes_lazy_shared_client(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_client = SimpleNamespace(aclose=AsyncMock())
    monkeypatch.setattr(redis_runtime, "_shared_redis_client", fake_client)

    await redis_runtime.close_redis_client(None)

    fake_client.aclose.assert_awaited_once()
    assert redis_runtime.get_shared_redis_client() is None
