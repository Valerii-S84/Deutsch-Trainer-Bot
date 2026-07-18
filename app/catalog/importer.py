from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.catalog.service import invalidate_local_catalog_cache
from app.catalog.snapshot import (
    CatalogImportOptions,
    CatalogImportReport,
    CatalogItemPayload,
    build_import_report,
    load_catalog_snapshot,
)
from app.db.models import QuizCatalog, QuizCatalogImportRun, QuizCatalogItem


class LocalCatalogImporter:
    """Import snapshot catalog data into local PostgreSQL catalog tables."""

    async def import_catalog(self, db: AsyncSession, options: CatalogImportOptions) -> CatalogImportReport:
        snapshot = load_catalog_snapshot(options)
        existing = await self._existing_items(db, catalog_id=options.catalog_id)
        report = build_import_report(snapshot, self._checksums(existing), dry_run=options.dry_run)
        conflict = await self._catalog_version_conflict(db, options)
        if conflict:
            return self._with_import_error(report, conflict)
        if options.dry_run:
            return report

        catalog = await self._upsert_catalog(db, snapshot)
        run = self._new_run(snapshot.catalog_id, options, report)
        db.add(run)
        await self._apply_items(db, snapshot.items, existing)
        self._finish_run(run, report)
        catalog.item_count = len(snapshot.items)
        await db.flush()
        await invalidate_local_catalog_cache(options.catalog_id)
        return report

    async def _existing_items(
        self,
        db: AsyncSession,
        *,
        catalog_id: str,
    ) -> dict[tuple[str, str], QuizCatalogItem]:
        result = await db.execute(select(QuizCatalogItem).where(QuizCatalogItem.catalog_id == catalog_id))
        return {(item.item_id, item.item_version): item for item in result.scalars()}

    async def _catalog_version_conflict(self, db: AsyncSession, options: CatalogImportOptions) -> str | None:
        result = await db.execute(select(QuizCatalog).where(QuizCatalog.catalog_id == options.catalog_id))
        catalog = result.scalar_one_or_none()
        if catalog is None or catalog.catalog_version == options.catalog_version:
            return None
        return (
            f"catalog_id {options.catalog_id!r} already exists with version "
            f"{catalog.catalog_version!r}; use a new catalog_id for side-by-side import"
        )

    async def _upsert_catalog(self, db: AsyncSession, snapshot) -> QuizCatalog:
        result = await db.execute(select(QuizCatalog).where(QuizCatalog.catalog_id == snapshot.catalog_id))
        catalog = result.scalar_one_or_none()
        if catalog is None:
            catalog = QuizCatalog(
                catalog_id=snapshot.catalog_id,
                catalog_version=snapshot.catalog_version,
                source=snapshot.source,
                checksum=snapshot.catalog_checksum,
                manifest_checksum=snapshot.manifest_checksum,
                source_path=str(snapshot.source_path),
                item_count=len(snapshot.items),
                catalog_metadata=snapshot.metadata,
            )
            db.add(catalog)
            return catalog

        catalog.checksum = snapshot.catalog_checksum
        catalog.manifest_checksum = snapshot.manifest_checksum
        catalog.source_path = str(snapshot.source_path)
        catalog.item_count = len(snapshot.items)
        catalog.catalog_metadata = snapshot.metadata
        catalog.imported_at = datetime.now(UTC)
        return catalog

    async def _apply_items(
        self,
        db: AsyncSession,
        items: tuple[CatalogItemPayload, ...],
        existing: dict[tuple[str, str], QuizCatalogItem],
    ) -> None:
        for item in items:
            current = existing.get((item.item_id, item.item_version))
            if current is None:
                db.add(QuizCatalogItem(**item.model_values()))
            elif current.checksum != item.checksum:
                self._update_item(current, item)

    def _update_item(self, current: QuizCatalogItem, item: CatalogItemPayload) -> None:
        for key, value in item.model_values().items():
            setattr(current, key, value)
        current.imported_at = datetime.now(UTC)

    def _new_run(
        self,
        catalog_id: str,
        options: CatalogImportOptions,
        report: CatalogImportReport,
    ) -> QuizCatalogImportRun:
        return QuizCatalogImportRun(
            catalog_id=catalog_id,
            catalog_version=options.catalog_version,
            source_path=str(options.source_path),
            manifest_checksum=report.manifest_checksum,
            dry_run=False,
            status="running",
            added_count=report.added_count,
            updated_count=report.updated_count,
            skipped_count=report.skipped_count,
            failed_count=report.failed_count,
            error_summary=self._error_summary(report),
        )

    def _finish_run(self, run: QuizCatalogImportRun, report: CatalogImportReport) -> None:
        run.status = report.status
        run.finished_at = datetime.now(UTC)

    def _with_import_error(self, report: CatalogImportReport, error: str) -> CatalogImportReport:
        return replace(
            report,
            added_count=0,
            updated_count=0,
            skipped_count=0,
            failed_count=report.failed_count + 1,
            errors=(*report.errors, error),
        )

    def _checksums(self, existing: dict[tuple[str, str], QuizCatalogItem]) -> dict[tuple[str, str], str]:
        return {key: item.checksum for key, item in existing.items()}

    def _error_summary(self, report: CatalogImportReport) -> dict[str, object] | None:
        if not report.errors and not report.warnings:
            return None
        return {"errors": list(report.errors), "warnings": list(report.warnings)}
