from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from redis.exceptions import RedisError

import app.catalog.service as catalog_service_module
from app.catalog.selection import LocalCatalogTheme
from app.catalog.service import LocalCatalogQuizService, invalidate_local_catalog_cache
from app.config import Settings


class FakeRedis:
    def __init__(self, *, fail_on_get: bool = False, fail_on_set: bool = False) -> None:
        self.fail_on_get = fail_on_get
        self.fail_on_set = fail_on_set
        self.values: dict[str, str] = {}
        self.get_calls: list[str] = []
        self.set_calls: list[tuple[str, str, int]] = []
        self.delete_calls: list[tuple[str, ...]] = []

    async def get(self, key: str) -> str | None:
        self.get_calls.append(key)
        if self.fail_on_get:
            raise RedisError("cache get failed")
        return self.values.get(key)

    async def set(self, key: str, value: str, *, ex: int) -> bool:
        self.set_calls.append((key, value, ex))
        if self.fail_on_set:
            raise RedisError("cache set failed")
        self.values[key] = value
        return True

    async def scan_iter(self, match: str):
        prefix = match.rstrip("*")
        for key in list(self.values):
            if key.startswith(prefix):
                yield key

    async def delete(self, *keys: str) -> int:
        self.delete_calls.append(keys)
        deleted = 0
        for key in keys:
            if key in self.values:
                deleted += 1
                self.values.pop(key)
        return deleted


class FakeSelector:
    selectable_statuses = ("reviewed", "active", "published")

    def __init__(self, *, themes: list[LocalCatalogTheme] | None = None, question=None) -> None:
        self.list_themes = AsyncMock(return_value=themes or [])
        self.next_question = AsyncMock(return_value=question)


@pytest.fixture
def local_catalog_settings() -> Settings:
    return Settings(ACTIVE_CATALOG_ID="cat-local", LOCAL_CATALOG_CACHE_ENABLED=True)


@pytest.mark.asyncio
async def test_catalog_version_reads_through_shared_redis_cache(
    monkeypatch: pytest.MonkeyPatch,
    local_catalog_settings: Settings,
) -> None:
    redis = FakeRedis()
    db = SimpleNamespace(scalar=AsyncMock(return_value="2026-06-30"))
    monkeypatch.setattr(catalog_service_module, "get_shared_redis_client", lambda: redis)
    service = LocalCatalogQuizService(local_catalog_settings)

    first = await service.catalog_version(db)
    second = await service.catalog_version(db)

    assert first == "2026-06-30"
    assert second == "2026-06-30"
    assert db.scalar.await_count == 1
    assert redis.get_calls == [
        "dtb:local_catalog:catalog_version:cat-local",
        "dtb:local_catalog:catalog_version:cat-local",
    ]
    assert redis.set_calls == [
        (
            "dtb:local_catalog:catalog_version:cat-local",
            '{"catalog_version": "2026-06-30"}',
            15,
        ),
    ]


@pytest.mark.asyncio
async def test_get_themes_reads_through_shared_redis_cache(
    monkeypatch: pytest.MonkeyPatch,
    local_catalog_settings: Settings,
) -> None:
    redis = FakeRedis()
    selector = FakeSelector(themes=[LocalCatalogTheme(theme_id="T01", theme_slug="alltag", item_count=4)])
    service = LocalCatalogQuizService(local_catalog_settings, selector=selector)
    catalog_version = AsyncMock(return_value="2026-06-30")
    monkeypatch.setattr(catalog_service_module, "get_shared_redis_client", lambda: redis)
    monkeypatch.setattr(service, "catalog_version", catalog_version)

    first = await service.get_themes(object(), level="A1")
    second = await service.get_themes(object(), level="A1")

    assert first.model_dump() == second.model_dump()
    assert [theme.theme for theme in first.themes] == ["alltag"]
    assert selector.list_themes.await_count == 1
    assert catalog_version.await_count == 1
    assert redis.set_calls[0][0] == "dtb:local_catalog:themes:cat-local:A1"
    assert redis.set_calls[0][2] == 15


@pytest.mark.asyncio
async def test_get_availability_reads_through_shared_redis_cache(
    monkeypatch: pytest.MonkeyPatch,
    local_catalog_settings: Settings,
) -> None:
    redis = FakeRedis()
    db = SimpleNamespace(scalar=AsyncMock(side_effect=[3, "2026-06-30"]))
    monkeypatch.setattr(catalog_service_module, "get_shared_redis_client", lambda: redis)
    service = LocalCatalogQuizService(local_catalog_settings)

    first = await service.get_availability(db, level="A1", theme="T01")
    second = await service.get_availability(db, level="A1", theme="T01")

    assert first.model_dump() == second.model_dump()
    assert first.available_items_count == 3
    assert first.active_items_count == 3
    assert first.content_version == "2026-06-30"
    assert db.scalar.await_count == 2
    assert redis.set_calls[-1][0] == "dtb:local_catalog:availability:cat-local:A1:T01"
    assert redis.set_calls[-1][2] == 15


@pytest.mark.asyncio
async def test_get_availability_falls_back_when_redis_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
    local_catalog_settings: Settings,
) -> None:
    redis = FakeRedis(fail_on_get=True, fail_on_set=True)
    db = SimpleNamespace(scalar=AsyncMock(side_effect=[2, "2026-06-30"]))
    monkeypatch.setattr(catalog_service_module, "get_shared_redis_client", lambda: redis)
    service = LocalCatalogQuizService(local_catalog_settings)

    response = await service.get_availability(db, level="A1", theme="T01")

    assert response.available_items_count == 2
    assert response.active_items_count == 2
    assert response.content_version == "2026-06-30"
    assert db.scalar.await_count == 2


@pytest.mark.asyncio
async def test_request_quiz_does_not_touch_catalog_cache(
    monkeypatch: pytest.MonkeyPatch,
    local_catalog_settings: Settings,
) -> None:
    redis = FakeRedis()
    selector = FakeSelector(question=None)
    monkeypatch.setattr(catalog_service_module, "get_shared_redis_client", lambda: redis)
    service = LocalCatalogQuizService(local_catalog_settings, selector=selector)

    response = await service.request_quiz(
        object(),
        level="A1",
        theme="T01",
        limit=1,
        user_context=None,
        seed_material="seed",
    )

    assert response.items == []
    assert response.returned_count == 0
    assert redis.get_calls == []
    assert redis.set_calls == []
    selector.next_question.assert_awaited_once()


@pytest.mark.asyncio
async def test_invalidate_local_catalog_cache_deletes_catalog_keys(
    monkeypatch: pytest.MonkeyPatch,
    local_catalog_settings: Settings,
) -> None:
    redis = FakeRedis()
    redis.values = {
        "dtb:local_catalog:themes:cat-local:A1": "{}",
        "dtb:local_catalog:availability:cat-local:A1:T01": "{}",
        "dtb:local_catalog:catalog_version:cat-local": "{}",
        "dtb:local_catalog:themes:other:A1": "{}",
    }
    monkeypatch.setattr(catalog_service_module, "get_shared_redis_client", lambda: redis)

    await invalidate_local_catalog_cache("cat-local", settings=local_catalog_settings)

    assert "dtb:local_catalog:themes:other:A1" in redis.values
    assert redis.delete_calls == [
        (
            "dtb:local_catalog:themes:cat-local:A1",
            "dtb:local_catalog:availability:cat-local:A1:T01",
            "dtb:local_catalog:catalog_version:cat-local",
        ),
    ]
