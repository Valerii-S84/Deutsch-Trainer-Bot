from __future__ import annotations

import ast
import csv
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.catalog.checksums import checksum_files, checksum_mapping, selection_key_from_checksum


SUPPORTED_LEVELS = {"A1", "A2", "B1", "B2", "C1", "C2"}
ACTIVE_ITEM_STATUSES = {"active", "published", "reviewed"}
REQUIRED_COLUMNS = (
    "item_id",
    "language",
    "sublevel",
    "theme_id",
    "stem_text",
    "options",
    "answer_key",
    "status",
    "version",
)


@dataclass(frozen=True)
class CatalogImportOptions:
    catalog_id: str
    catalog_version: str
    source_path: Path
    source: str = "production_quiz_bank_snapshot"
    dry_run: bool = False


@dataclass(frozen=True)
class CatalogItemPayload:
    catalog_id: str
    catalog_version: str
    item_id: str
    item_version: str
    language: str
    level: str
    sublevel: str
    theme_id: str
    theme_slug: str | None
    prompt: str | None
    stem_text: str
    options: list[Any]
    answer_key: str
    explanation: str | None
    tags: list[str]
    status: str
    source: str
    source_path: str
    checksum: str
    selection_key: int
    metadata: dict[str, Any]
    theme: str | None = None
    subtheme_id: str | None = None
    objective_id: str | None = None
    pattern_id: str | None = None
    difficulty_band: str | None = None
    register: str | None = None

    @property
    def is_active(self) -> bool:
        return self.status.lower() in ACTIVE_ITEM_STATUSES

    def model_values(self) -> dict[str, Any]:
        return {
            "catalog_id": self.catalog_id,
            "catalog_version": self.catalog_version,
            "item_id": self.item_id,
            "item_version": self.item_version,
            "language": self.language,
            "level": self.level,
            "sublevel": self.sublevel,
            "theme_id": self.theme_id,
            "theme": self.theme,
            "theme_slug": self.theme_slug,
            "subtheme_id": self.subtheme_id,
            "objective_id": self.objective_id,
            "pattern_id": self.pattern_id,
            "difficulty_band": self.difficulty_band,
            "register": self.register,
            "prompt": self.prompt,
            "stem_text": self.stem_text,
            "options": self.options,
            "answer_key": self.answer_key,
            "explanation": self.explanation,
            "tags": self.tags,
            "status": self.status,
            "source": self.source,
            "source_path": self.source_path,
            "checksum": self.checksum,
            "selection_key": self.selection_key,
            "is_active": self.is_active,
            "item_metadata": self.metadata,
        }


@dataclass(frozen=True)
class CatalogSnapshot:
    catalog_id: str
    catalog_version: str
    source: str
    source_path: Path
    manifest_checksum: str
    catalog_checksum: str
    manifest_item_count: int
    items: tuple[CatalogItemPayload, ...]
    warnings: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CatalogImportReport:
    catalog_id: str
    catalog_version: str
    source_path: str
    dry_run: bool
    manifest_checksum: str
    catalog_checksum: str
    manifest_item_count: int
    actual_item_count: int
    added_count: int
    updated_count: int
    skipped_count: int
    failed_count: int
    warnings: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()

    @property
    def status(self) -> str:
        if self.errors and self.actual_item_count == 0:
            return "failed"
        if self.errors:
            return "completed_with_errors"
        return "completed"


def load_catalog_snapshot(options: CatalogImportOptions) -> CatalogSnapshot:
    root = options.source_path.resolve()
    registry = _load_registry(root)
    theme_slugs = _theme_slugs(registry["themes"])
    items, errors, file_counts = _load_items(options, registry["manifest"], theme_slugs)
    warnings = _count_warnings(registry["manifest"], file_counts)
    checksum = _catalog_checksum(items, file_counts)
    metadata = {
        "manifest_rows": len(registry["manifest"]),
        "theme_rows": len(registry["themes"]),
        "file_counts": file_counts,
    }
    return CatalogSnapshot(
        catalog_id=options.catalog_id,
        catalog_version=options.catalog_version,
        source=options.source,
        source_path=root,
        manifest_checksum=registry["checksum"],
        catalog_checksum=checksum,
        manifest_item_count=_manifest_total(registry["manifest"]),
        items=tuple(items),
        warnings=tuple(warnings),
        errors=tuple(errors),
        metadata=metadata,
    )


def build_import_report(
    snapshot: CatalogSnapshot,
    existing_checksums: dict[tuple[str, str], str],
    *,
    dry_run: bool,
) -> CatalogImportReport:
    added, updated, skipped = plan_item_changes(snapshot.items, existing_checksums)
    return CatalogImportReport(
        catalog_id=snapshot.catalog_id,
        catalog_version=snapshot.catalog_version,
        source_path=str(snapshot.source_path),
        dry_run=dry_run,
        manifest_checksum=snapshot.manifest_checksum,
        catalog_checksum=snapshot.catalog_checksum,
        manifest_item_count=snapshot.manifest_item_count,
        actual_item_count=len(snapshot.items),
        added_count=added,
        updated_count=updated,
        skipped_count=skipped,
        failed_count=len(snapshot.errors),
        warnings=snapshot.warnings,
        errors=snapshot.errors,
    )


def plan_item_changes(
    items: tuple[CatalogItemPayload, ...],
    existing_checksums: dict[tuple[str, str], str],
) -> tuple[int, int, int]:
    added = updated = skipped = 0
    for item in items:
        current = existing_checksums.get((item.item_id, item.item_version))
        if current is None:
            added += 1
        elif current == item.checksum:
            skipped += 1
        else:
            updated += 1
    return added, updated, skipped


def _load_registry(root: Path) -> dict[str, Any]:
    registry_root = root / "_registry"
    manifest_path = registry_root / "production_manifest.csv"
    theme_path = registry_root / "theme_registry.csv"
    migration_path = registry_root / "migration_map.csv"
    paths = [manifest_path, theme_path]
    if migration_path.exists():
        paths.append(migration_path)
    return {
        "manifest": _read_csv(manifest_path),
        "themes": _read_csv(theme_path),
        "checksum": checksum_files(paths),
    }


def _load_items(
    options: CatalogImportOptions,
    manifest_rows: list[dict[str, str]],
    theme_slugs: dict[str, str],
) -> tuple[list[CatalogItemPayload], list[str], dict[str, int]]:
    items: list[CatalogItemPayload] = []
    errors: list[str] = []
    file_counts: dict[str, int] = {}
    root = options.source_path.resolve()
    for manifest_row in manifest_rows:
        csv_path = _resolve_production_file(root, manifest_row["production_file"])
        display_path = _display_path(root, csv_path)
        rows = _read_csv(csv_path)
        file_counts[manifest_row["production_file"]] = len(rows)
        for row_number, row in enumerate(rows, start=2):
            payload = _row_payload(options, row, theme_slugs, display_path, row_number)
            if isinstance(payload, str):
                errors.append(payload)
            else:
                items.append(payload)
    return items, errors, file_counts


def _row_payload(
    options: CatalogImportOptions,
    row: dict[str, str],
    theme_slugs: dict[str, str],
    source_path: str,
    row_number: int,
) -> CatalogItemPayload | str:
    error = _validate_required(row, source_path, row_number)
    if error:
        return error
    parsed_options = _parse_options(row["options"])
    if isinstance(parsed_options, str):
        return f"{source_path}:{row_number}: {parsed_options}"
    answer_error = _validate_answer_key(row["answer_key"], parsed_options)
    if answer_error:
        return f"{source_path}:{row_number}: {answer_error}"
    level = row["sublevel"].strip().upper()
    metadata = _row_metadata(row, source_path, row_number)
    checksum = checksum_mapping(_checksum_payload(row, parsed_options, metadata))
    return CatalogItemPayload(
        catalog_id=options.catalog_id,
        catalog_version=options.catalog_version,
        item_id=row["item_id"].strip(),
        item_version=row["version"].strip(),
        language=row["language"].strip().lower(),
        level=level,
        sublevel=level,
        theme_id=row["theme_id"].strip(),
        theme_slug=theme_slugs.get(row["theme_id"].strip()),
        prompt=_clean(row.get("prompt")),
        stem_text=row["stem_text"].strip(),
        options=parsed_options,
        answer_key=row["answer_key"].strip(),
        explanation=_clean(row.get("explanation")),
        tags=_parse_tags(row.get("tags", "")),
        status=row["status"].strip(),
        source=_clean(row.get("source_type")) or options.source,
        source_path=source_path,
        checksum=checksum,
        selection_key=selection_key_from_checksum(checksum),
        metadata=metadata,
        subtheme_id=_clean(row.get("subtheme_id")),
        objective_id=_clean(row.get("objective_id")),
        pattern_id=_clean(row.get("pattern_id")),
        difficulty_band=_clean(row.get("difficulty_band")),
        register=_clean(row.get("register")),
    )


def _validate_required(row: dict[str, str], source_path: str, row_number: int) -> str | None:
    missing = [column for column in REQUIRED_COLUMNS if not row.get(column, "").strip()]
    if missing:
        return f"{source_path}:{row_number}: missing required columns: {','.join(missing)}"
    if row["sublevel"].strip().upper() not in SUPPORTED_LEVELS:
        return f"{source_path}:{row_number}: unsupported CEFR level {row['sublevel']}"
    return None


def _parse_options(raw: str) -> list[Any] | str:
    for parser in (json.loads, ast.literal_eval):
        try:
            parsed = parser(raw)
        except (SyntaxError, ValueError, TypeError, json.JSONDecodeError):
            continue
        if isinstance(parsed, list) and len(parsed) >= 2:
            return parsed
    return "options must be a JSON or Python list with at least two choices"


def _validate_answer_key(answer_key: str, options: list[Any]) -> str | None:
    if not answer_key.strip().isdigit():
        return "answer_key must be a zero-based option index"
    if int(answer_key) >= len(options):
        return "answer_key points outside options"
    return None


def _parse_tags(raw: str) -> list[str]:
    return [value.strip() for value in raw.replace(",", ";").split(";") if value.strip()]


def _row_metadata(row: dict[str, str], source_path: str, row_number: int) -> dict[str, Any]:
    keys = (
        "level_band",
        "coverage_cell_id",
        "provenance_note",
        "created_at",
        "updated_at",
        "reviewed_at",
        "level_locked",
        "locked_at",
    )
    metadata = {key: row.get(key) for key in keys if row.get(key)}
    metadata["source_file"] = source_path
    metadata["row_number"] = row_number
    return metadata


def _checksum_payload(row: dict[str, str], options: list[Any], metadata: dict[str, Any]) -> dict[str, Any]:
    return {
        "item_id": row["item_id"].strip(),
        "item_version": row["version"].strip(),
        "language": row["language"].strip().lower(),
        "level": row["sublevel"].strip().upper(),
        "theme_id": row["theme_id"].strip(),
        "stem_text": row["stem_text"].strip(),
        "options": options,
        "answer_key": row["answer_key"].strip(),
        "explanation": _clean(row.get("explanation")),
        "tags": _parse_tags(row.get("tags", "")),
        "status": row["status"].strip(),
        "metadata": metadata,
    }


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _theme_slugs(rows: list[dict[str, str]]) -> dict[str, str]:
    return {row["theme_id"].strip(): row["theme_slug"].strip() for row in rows if row.get("theme_id")}


def _resolve_production_file(root: Path, production_file: str) -> Path:
    candidate = Path(production_file)
    if candidate.is_absolute():
        return candidate
    if candidate.parts and candidate.parts[0] == root.name:
        return root.parent / candidate
    return root / candidate


def _display_path(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _count_warnings(manifest_rows: list[dict[str, str]], file_counts: dict[str, int]) -> list[str]:
    warnings: list[str] = []
    for row in manifest_rows:
        expected = int(row.get("item_count") or 0)
        actual = file_counts.get(row["production_file"], 0)
        if expected != actual:
            warnings.append(f"{row['production_file']}: manifest item_count={expected}, actual={actual}")
    return warnings


def _manifest_total(rows: list[dict[str, str]]) -> int:
    return sum(int(row.get("item_count") or 0) for row in rows)


def _catalog_checksum(items: list[CatalogItemPayload], file_counts: dict[str, int]) -> str:
    payload = {
        "files": file_counts,
        "items": [(item.item_id, item.item_version, item.checksum) for item in sorted(items, key=_item_sort_key)],
    }
    return checksum_mapping(payload)


def _item_sort_key(item: CatalogItemPayload) -> tuple[str, str]:
    return item.item_id, item.item_version


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None
