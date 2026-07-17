from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from app.db.models import QuizCatalog, QuizCatalogImportRun, QuizCatalogItem
from app.repositories.quiz_catalogs import (
    QuizCatalogImportRunFinish,
    QuizCatalogImportRunStart,
    QuizCatalogItemQuery,
    QuizCatalogItemUpsert,
    QuizCatalogRepository,
    QuizCatalogUpsert,
)


class _FakeScalarResult:
    def __init__(self, rows: list[object]) -> None:
        self._rows = rows

    def all(self) -> list[object]:
        return self._rows


class _FakeExecuteResult:
    def __init__(self, rows: list[object]) -> None:
        self._rows = rows

    def scalars(self) -> _FakeScalarResult:
        return _FakeScalarResult(self._rows)


class _FakeSession:
    def __init__(
        self,
        *,
        scalar_results: list[object | None] | None = None,
        execute_results: list[list[object]] | None = None,
    ) -> None:
        self.added: list[object] = []
        self.scalar_results = scalar_results or []
        self.execute_results = execute_results or []

    def get_bind(self) -> SimpleNamespace:
        return SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))

    def add(self, instance: object) -> None:
        self.added.append(instance)

    async def scalar(self, _query: object) -> object | None:
        if not self.scalar_results:
            return None
        return self.scalar_results.pop(0)

    async def execute(self, _query: object) -> _FakeExecuteResult:
        if not self.execute_results:
            return _FakeExecuteResult([])
        return _FakeExecuteResult(self.execute_results.pop(0))


@pytest.mark.asyncio
async def test_upsert_catalog_creates_and_updates_version() -> None:
    repository = QuizCatalogRepository()
    db = _FakeSession(scalar_results=[None])

    created = await repository.upsert_catalog(
        db,  # type: ignore[arg-type]
        data=QuizCatalogUpsert(
            catalog_id="production-de",
            catalog_version="2026-07-17",
            source="ProductionQuizBank",
            checksum="checksum-1",
            item_count=10,
            catalog_metadata={"source": "test"},
        ),
    )

    db.scalar_results.append(created)
    updated = await repository.upsert_catalog(
        db,  # type: ignore[arg-type]
        data=QuizCatalogUpsert(
            catalog_id="production-de",
            catalog_version="2026-07-17",
            source="ProductionQuizBank",
            checksum="checksum-2",
            item_count=12,
            is_active=False,
            catalog_metadata={"source": "updated"},
        ),
    )

    assert db.added == [created]
    assert updated is created
    assert updated.checksum == "checksum-2"
    assert updated.item_count == 12
    assert updated.catalog_metadata == {"source": "updated"}
    assert updated.is_active is False


@pytest.mark.asyncio
async def test_list_active_catalogs_returns_execute_results() -> None:
    catalog = QuizCatalog(
        catalog_id="production-de",
        catalog_version="2026-07-17",
        source="ProductionQuizBank",
        checksum="checksum",
    )
    db = _FakeSession(execute_results=[[catalog]])

    result = await QuizCatalogRepository().list_active_catalogs(db)  # type: ignore[arg-type]

    assert result == [catalog]


@pytest.mark.asyncio
async def test_upsert_item_creates_and_updates_catalog_item() -> None:
    repository = QuizCatalogRepository()
    db = _FakeSession(scalar_results=[None])

    created = await repository.upsert_item(
        db,  # type: ignore[arg-type]
        data=QuizCatalogItemUpsert(
            catalog_id="production-de",
            catalog_version="2026-07-17",
            item_id="item-1",
            item_version="v1",
            level="A1",
            theme_id="T01",
            status="active",
            source="csv",
            checksum="item-checksum-1",
            selection_key=20,
        ),
    )

    db.scalar_results.append(created)
    updated = await repository.upsert_item(
        db,  # type: ignore[arg-type]
        data=QuizCatalogItemUpsert(
            catalog_id="production-de",
            catalog_version="2026-07-17",
            item_id="item-1",
            item_version="v1",
            level="A1",
            theme_id="T01",
            status="active",
            source="csv",
            checksum="item-checksum-1b",
            selection_key=30,
            item_metadata={"difficulty": "low"},
        ),
    )

    assert db.added == [created]
    assert updated is created
    assert updated.checksum == "item-checksum-1b"
    assert updated.selection_key == 30
    assert updated.item_metadata == {"difficulty": "low"}


@pytest.mark.asyncio
async def test_list_active_items_returns_execute_results() -> None:
    first = QuizCatalogItem(
        catalog_id="production-de",
        catalog_version="2026-07-17",
        item_id="item-1",
        item_version="v1",
        level="A1",
        theme_id="T01",
        status="active",
        source="csv",
        checksum="checksum-1",
        selection_key=10,
    )
    second = QuizCatalogItem(
        catalog_id="production-de",
        catalog_version="2026-07-17",
        item_id="item-2",
        item_version="v1",
        level="A1",
        theme_id="T01",
        status="active",
        source="csv",
        checksum="checksum-2",
        selection_key=20,
    )
    db = _FakeSession(execute_results=[[first, second]])

    result = await QuizCatalogRepository().list_active_items(  # type: ignore[arg-type]
        db,
        query_filter=QuizCatalogItemQuery(
            catalog_id="production-de",
            catalog_version="2026-07-17",
            level="A1",
            theme_id="T01",
        ),
    )

    assert result == [first, second]


@pytest.mark.asyncio
async def test_import_run_start_and_finish_records_counts() -> None:
    db = _FakeSession()
    repository = QuizCatalogRepository()

    import_run = await repository.start_import_run(
        db,  # type: ignore[arg-type]
        data=QuizCatalogImportRunStart(
            catalog_id="production-de",
            catalog_version="2026-07-17",
            source_path="ProductionQuizBank",
            manifest_checksum="manifest-checksum",
            dry_run=True,
        ),
    )
    finished = await repository.finish_import_run(
        db,  # type: ignore[arg-type]
        import_run,
        data=QuizCatalogImportRunFinish(
            status="failed",
            added_count=3,
            updated_count=2,
            skipped_count=1,
            failed_count=4,
            error_summary={"row": "invalid"},
        ),
    )

    assert isinstance(import_run, QuizCatalogImportRun)
    assert db.added == [import_run]
    assert finished is import_run
    assert finished.status == "failed"
    assert finished.dry_run is True
    assert finished.added_count == 3
    assert finished.updated_count == 2
    assert finished.skipped_count == 1
    assert finished.failed_count == 4
    assert finished.error_summary == {"row": "invalid"}
    assert finished.finished_at is not None
