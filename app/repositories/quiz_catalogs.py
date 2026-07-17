from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import QuizCatalog, QuizCatalogImportRun, QuizCatalogItem
from app.repositories.sqlite_compat import next_sqlite_id_if_needed


@dataclass(frozen=True)
class QuizCatalogUpsert:
    catalog_id: str
    catalog_version: str
    source: str
    checksum: str
    manifest_checksum: str | None = None
    source_path: str | None = None
    item_count: int = 0
    is_active: bool = True
    catalog_metadata: dict[str, object] | None = None


@dataclass(frozen=True)
class QuizCatalogItemUpsert:
    catalog_id: str
    catalog_version: str
    item_id: str
    item_version: str
    level: str
    theme_id: str
    status: str
    source: str
    checksum: str
    selection_key: int
    language: str = "de"
    sublevel: str | None = None
    theme: str | None = None
    theme_slug: str | None = None
    subtheme_id: str | None = None
    objective_id: str | None = None
    pattern_id: str | None = None
    difficulty_band: str | None = None
    register: str | None = None
    tags: list[object] | None = None
    source_path: str | None = None
    is_active: bool = True
    item_metadata: dict[str, object] | None = None


@dataclass(frozen=True)
class QuizCatalogItemQuery:
    catalog_id: str
    catalog_version: str
    language: str = "de"
    level: str | None = None
    theme_id: str | None = None
    sublevel: str | None = None
    status: str = "active"
    limit: int | None = None


@dataclass(frozen=True)
class QuizCatalogImportRunStart:
    source_path: str
    catalog_id: str | None = None
    catalog_version: str | None = None
    manifest_checksum: str | None = None
    dry_run: bool = False
    status: str = "started"


@dataclass(frozen=True)
class QuizCatalogImportRunFinish:
    status: str
    added_count: int = 0
    updated_count: int = 0
    skipped_count: int = 0
    failed_count: int = 0
    error_summary: dict[str, Any] | None = None
    finished_at: datetime | None = None


class QuizCatalogRepository:
    """Persistence helpers for imported local quiz catalog metadata."""

    async def get_catalog(
        self,
        db: AsyncSession,
        *,
        catalog_id: str,
        catalog_version: str,
    ) -> QuizCatalog | None:
        return await db.scalar(
            select(QuizCatalog).where(
                QuizCatalog.catalog_id == catalog_id,
                QuizCatalog.catalog_version == catalog_version,
            ),
        )

    async def list_active_catalogs(self, db: AsyncSession) -> list[QuizCatalog]:
        result = await db.execute(
            select(QuizCatalog)
            .where(QuizCatalog.is_active.is_(True))
            .order_by(QuizCatalog.catalog_id.asc(), QuizCatalog.catalog_version.asc()),
        )
        return list(result.scalars().all())

    async def upsert_catalog(
        self,
        db: AsyncSession,
        *,
        data: QuizCatalogUpsert,
    ) -> QuizCatalog:
        existing = await self.get_catalog(db, catalog_id=data.catalog_id, catalog_version=data.catalog_version)
        if existing is not None:
            existing.source = data.source
            existing.checksum = data.checksum
            existing.manifest_checksum = data.manifest_checksum
            existing.source_path = data.source_path
            existing.item_count = max(0, data.item_count)
            existing.is_active = data.is_active
            existing.catalog_metadata = data.catalog_metadata
            existing.imported_at = datetime.now(UTC)
            return existing

        catalog = QuizCatalog(
            id=await next_sqlite_id_if_needed(db, QuizCatalog),
            catalog_id=data.catalog_id,
            catalog_version=data.catalog_version,
            source=data.source,
            checksum=data.checksum,
            manifest_checksum=data.manifest_checksum,
            source_path=data.source_path,
            item_count=max(0, data.item_count),
            is_active=data.is_active,
            catalog_metadata=data.catalog_metadata,
            imported_at=datetime.now(UTC),
        )
        db.add(catalog)
        return catalog

    async def get_item(
        self,
        db: AsyncSession,
        *,
        catalog_id: str,
        catalog_version: str,
        item_id: str,
        item_version: str,
    ) -> QuizCatalogItem | None:
        return await db.scalar(
            select(QuizCatalogItem).where(
                QuizCatalogItem.catalog_id == catalog_id,
                QuizCatalogItem.catalog_version == catalog_version,
                QuizCatalogItem.item_id == item_id,
                QuizCatalogItem.item_version == item_version,
            ),
        )

    async def upsert_item(
        self,
        db: AsyncSession,
        *,
        data: QuizCatalogItemUpsert,
    ) -> QuizCatalogItem:
        existing = await self.get_item(
            db,
            catalog_id=data.catalog_id,
            catalog_version=data.catalog_version,
            item_id=data.item_id,
            item_version=data.item_version,
        )
        if existing is None:
            existing = QuizCatalogItem(
                id=await next_sqlite_id_if_needed(db, QuizCatalogItem),
                catalog_id=data.catalog_id,
                catalog_version=data.catalog_version,
                item_id=data.item_id,
                item_version=data.item_version,
            )
            db.add(existing)

        self._apply_item_data(existing, data)
        existing.imported_at = datetime.now(UTC)
        return existing

    async def list_active_items(
        self,
        db: AsyncSession,
        *,
        query_filter: QuizCatalogItemQuery,
    ) -> list[QuizCatalogItem]:
        query = select(QuizCatalogItem).where(
            QuizCatalogItem.catalog_id == query_filter.catalog_id,
            QuizCatalogItem.catalog_version == query_filter.catalog_version,
            QuizCatalogItem.language == query_filter.language,
            QuizCatalogItem.status == query_filter.status,
            QuizCatalogItem.is_active.is_(True),
        )
        if query_filter.level is not None:
            query = query.where(QuizCatalogItem.level == query_filter.level)
        if query_filter.theme_id is not None:
            query = query.where(QuizCatalogItem.theme_id == query_filter.theme_id)
        if query_filter.sublevel is not None:
            query = query.where(QuizCatalogItem.sublevel == query_filter.sublevel)
        if query_filter.limit is not None:
            query = query.limit(max(0, query_filter.limit))

        result = await db.execute(query.order_by(QuizCatalogItem.selection_key.asc(), QuizCatalogItem.id.asc()))
        return list(result.scalars().all())

    async def start_import_run(
        self,
        db: AsyncSession,
        *,
        data: QuizCatalogImportRunStart,
    ) -> QuizCatalogImportRun:
        import_run = QuizCatalogImportRun(
            id=await next_sqlite_id_if_needed(db, QuizCatalogImportRun),
            catalog_id=data.catalog_id,
            catalog_version=data.catalog_version,
            source_path=data.source_path,
            manifest_checksum=data.manifest_checksum,
            dry_run=data.dry_run,
            status=data.status,
            started_at=datetime.now(UTC),
        )
        db.add(import_run)
        return import_run

    async def finish_import_run(
        self,
        _db: AsyncSession,
        import_run: QuizCatalogImportRun,
        *,
        data: QuizCatalogImportRunFinish,
    ) -> QuizCatalogImportRun:
        import_run.status = data.status
        import_run.added_count = max(0, data.added_count)
        import_run.updated_count = max(0, data.updated_count)
        import_run.skipped_count = max(0, data.skipped_count)
        import_run.failed_count = max(0, data.failed_count)
        import_run.error_summary = data.error_summary
        import_run.finished_at = data.finished_at or datetime.now(UTC)
        return import_run

    @staticmethod
    def _apply_item_data(item: QuizCatalogItem, data: QuizCatalogItemUpsert) -> None:
        item.language = data.language
        item.level = data.level
        item.sublevel = data.sublevel
        item.theme_id = data.theme_id
        item.theme = data.theme
        item.theme_slug = data.theme_slug
        item.subtheme_id = data.subtheme_id
        item.objective_id = data.objective_id
        item.pattern_id = data.pattern_id
        item.difficulty_band = data.difficulty_band
        item.register = data.register
        item.tags = data.tags
        item.status = data.status
        item.source = data.source
        item.source_path = data.source_path
        item.checksum = data.checksum
        item.selection_key = data.selection_key
        item.is_active = data.is_active
        item.item_metadata = data.item_metadata
