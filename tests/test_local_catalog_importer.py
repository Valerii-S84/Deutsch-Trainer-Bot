from __future__ import annotations

import asyncio
import csv
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.catalog.importer import LocalCatalogImporter
from app.catalog.snapshot import (
    CatalogImportOptions,
    build_import_report,
    load_catalog_snapshot,
    plan_item_changes,
)
from app.db import models  # noqa: F401
from app.db.base import Base
from app.db.models import QuizCatalogImportRun, QuizCatalogItem


HEADER = [
    "item_id",
    "language",
    "level_band",
    "sublevel",
    "theme_id",
    "subtheme_id",
    "objective_id",
    "pattern_id",
    "difficulty_band",
    "register",
    "prompt",
    "stem_text",
    "options",
    "answer_key",
    "explanation",
    "tags",
    "coverage_cell_id",
    "status",
    "version",
    "source_type",
    "provenance_note",
    "created_at",
    "updated_at",
    "reviewed_at",
    "level_locked",
    "locked_at",
]


def test_snapshot_loader_parses_manifest_and_mixed_option_formats(tmp_path: Path) -> None:
    root = _snapshot(tmp_path, manifest_count=3, rows=[_row("q1"), _row("q2", options="['a', 'b']", level="C2")])

    snapshot = load_catalog_snapshot(_options(root))

    assert len(snapshot.items) == 2
    assert snapshot.items[0].options == ["a", "b", "c"]
    assert snapshot.items[1].options == ["a", "b"]
    assert snapshot.items[1].level == "C2"
    assert snapshot.items[0].tags == ["theme:t01", "level:a1"]
    assert snapshot.items[0].selection_key > 0
    assert snapshot.warnings == ("ProductionQuizBank/T01/T01_A1.csv: manifest item_count=3, actual=2",)


def test_snapshot_loader_reports_invalid_rows(tmp_path: Path) -> None:
    root = _snapshot(tmp_path, rows=[_row("q1", answer_key="5")])

    snapshot = load_catalog_snapshot(_options(root))
    report = build_import_report(snapshot, {}, dry_run=True)

    assert snapshot.items == ()
    assert report.failed_count == 1
    assert "answer_key points outside options" in report.errors[0]
    assert report.status == "failed"


def test_import_plan_counts_added_updated_and_skipped(tmp_path: Path) -> None:
    root = _snapshot(tmp_path, rows=[_row("q1"), _row("q2")])
    snapshot = load_catalog_snapshot(_options(root))
    existing = {
        ("q1", "1.0"): snapshot.items[0].checksum,
        ("q2", "1.0"): "different-checksum",
    }

    assert plan_item_changes(snapshot.items, existing) == (0, 1, 1)


def test_dry_run_report_has_idempotent_summary(tmp_path: Path) -> None:
    root = _snapshot(tmp_path, rows=[_row("q1"), _row("q2")])
    snapshot = load_catalog_snapshot(_options(root))
    existing = {(item.item_id, item.item_version): item.checksum for item in snapshot.items}

    report = build_import_report(snapshot, existing, dry_run=True)

    assert report.dry_run is True
    assert report.added_count == 0
    assert report.updated_count == 0
    assert report.skipped_count == 2
    assert report.failed_count == 0


def test_importer_persists_items_idempotently_with_sqlalchemy(tmp_path: Path) -> None:
    root = _snapshot(tmp_path, rows=[_row("q1"), _row("q2")])

    first, second, item_count, run_count = asyncio.run(_run_import_twice(root))

    assert (first.added_count, first.skipped_count) == (2, 0)
    assert (second.added_count, second.skipped_count) == (0, 2)
    assert item_count == 2
    assert run_count == 2


async def _run_import_twice(root: Path) -> tuple[object, object, int, int]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    first = await _run_import(session_factory, root)
    second = await _run_import(session_factory, root)
    async with session_factory() as session:
        item_count = await session.scalar(select(func.count()).select_from(QuizCatalogItem))
        run_count = await session.scalar(select(func.count()).select_from(QuizCatalogImportRun))
    await engine.dispose()
    return first, second, int(item_count or 0), int(run_count or 0)


async def _run_import(session_factory, root: Path):
    async with session_factory() as session:
        async with session.begin():
            return await LocalCatalogImporter().import_catalog(session, _options(root, dry_run=False))


def _options(root: Path, *, dry_run: bool = True) -> CatalogImportOptions:
    return CatalogImportOptions(
        catalog_id="catalog-2026-06-30",
        catalog_version="2026-06-30",
        source_path=root,
        dry_run=dry_run,
    )


def _snapshot(tmp_path: Path, *, rows: list[dict[str, str]], manifest_count: int | None = None) -> Path:
    root = tmp_path / "ProductionQuizBank"
    registry = root / "_registry"
    data_dir = root / "T01"
    registry.mkdir(parents=True)
    data_dir.mkdir()
    _write_csv(data_dir / "T01_A1.csv", HEADER, rows)
    _write_registry(registry, manifest_count if manifest_count is not None else len(rows))
    return root


def _write_registry(registry: Path, item_count: int) -> None:
    _write_csv(
        registry / "production_manifest.csv",
        ["production_file", "theme_id", "theme_slug", "cefr_level", "item_count", "source_file_count", "source_row_count"],
        [{"production_file": "ProductionQuizBank/T01/T01_A1.csv", "theme_id": "T01", "theme_slug": "identity", "cefr_level": "A1", "item_count": str(item_count), "source_file_count": "1", "source_row_count": str(item_count)}],
    )
    _write_csv(
        registry / "theme_registry.csv",
        ["theme_id", "theme_slug", "theme_folder", "production_path"],
        [{"theme_id": "T01", "theme_slug": "identity", "theme_folder": "T01", "production_path": "ProductionQuizBank/T01"}],
    )
    _write_csv(registry / "migration_map.csv", ["item_id"], [])


def _write_csv(path: Path, header: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=header)
        writer.writeheader()
        writer.writerows(rows)


def _row(item_id: str, *, options: str = '["a", "b", "c"]', level: str = "A1", answer_key: str = "1") -> dict[str, str]:
    row = {key: "" for key in HEADER}
    row.update(
        {
            "item_id": item_id,
            "language": "de",
            "level_band": "A1-A2",
            "sublevel": level,
            "theme_id": "T01",
            "prompt": "Was passt?",
            "stem_text": "Hallo ___",
            "options": options,
            "answer_key": answer_key,
            "tags": "theme:t01;level:a1",
            "status": "reviewed",
            "version": "1.0",
            "source_type": "snapshot",
        },
    )
    return row
