from __future__ import annotations

import ast
import csv
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


MANIFEST_PATH = Path("_registry") / "production_manifest.csv"
REQUIRED_MANIFEST_COLUMNS = {
    "production_file",
    "theme_id",
    "theme_slug",
    "cefr_level",
    "item_count",
    "source_file_count",
    "source_row_count",
}
REQUIRED_ITEM_COLUMNS = {
    "item_id",
    "language",
    "sublevel",
    "theme_id",
    "objective_id",
    "pattern_id",
    "difficulty_band",
    "register",
    "options",
    "answer_key",
    "tags",
    "status",
    "version",
    "source_type",
}


@dataclass(frozen=True)
class CatalogManifestEntry:
    production_file: Path
    theme_id: str
    theme_slug: str
    cefr_level: str
    item_count: int
    source_file_count: int
    source_row_count: int


@dataclass(frozen=True)
class CatalogSourceItem:
    item_id: str
    item_version: str
    language: str
    level: str
    sublevel: str | None
    theme_id: str
    theme_slug: str
    objective_id: str | None
    pattern_id: str | None
    difficulty_band: str | None
    register: str | None
    tags: list[str]
    status: str
    source: str
    source_path: str
    checksum: str
    selection_key: int


class CatalogSourceError(ValueError):
    """Raised when a local quiz catalog source file is malformed."""


class QuizCatalogSourceReader:
    """Read and validate local quiz catalog source files without importing them."""

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)

    def read_manifest(self) -> list[CatalogManifestEntry]:
        rows = self._read_csv(self.root / MANIFEST_PATH, required_columns=REQUIRED_MANIFEST_COLUMNS)
        entries = [self._manifest_entry(row) for row in rows]
        return entries

    def read_items(self, entry: CatalogManifestEntry) -> list[CatalogSourceItem]:
        item_path = self._resolve_production_file(entry.production_file)
        rows = self._read_csv(item_path, required_columns=REQUIRED_ITEM_COLUMNS)
        items = [self._source_item(row, entry=entry, selection_key=index) for index, row in enumerate(rows, start=1)]
        return items

    def manifest_checksum(self) -> str:
        return self._file_checksum(self.root / MANIFEST_PATH)

    def file_checksum(self, production_file: Path) -> str:
        return self._file_checksum(self._resolve_production_file(production_file))

    def _resolve_production_file(self, production_file: Path) -> Path:
        parts = production_file.parts
        if parts and parts[0] == self.root.name:
            return self.root.joinpath(*parts[1:])
        return self.root / production_file

    def _manifest_entry(self, row: dict[str, str]) -> CatalogManifestEntry:
        return CatalogManifestEntry(
            production_file=Path(row["production_file"]),
            theme_id=row["theme_id"],
            theme_slug=row["theme_slug"],
            cefr_level=row["cefr_level"],
            item_count=self._int_field(row, "item_count"),
            source_file_count=self._int_field(row, "source_file_count"),
            source_row_count=self._int_field(row, "source_row_count"),
        )

    def _source_item(
        self,
        row: dict[str, str],
        *,
        entry: CatalogManifestEntry,
        selection_key: int,
    ) -> CatalogSourceItem:
        self._validate_item_scope(row, entry=entry)
        options = self._options(row)
        answer_key = self._int_field(row, "answer_key")
        if answer_key < 0 or answer_key >= len(options):
            raise CatalogSourceError(f"Invalid answer_key for {row['item_id']}: {answer_key}")

        return CatalogSourceItem(
            item_id=row["item_id"],
            item_version=row["version"],
            language=row["language"],
            level=entry.cefr_level,
            sublevel=self._optional(row, "sublevel"),
            theme_id=row["theme_id"],
            theme_slug=entry.theme_slug,
            objective_id=self._optional(row, "objective_id"),
            pattern_id=self._optional(row, "pattern_id"),
            difficulty_band=self._optional(row, "difficulty_band"),
            register=self._optional(row, "register"),
            tags=self._tags(row),
            status=row["status"],
            source=row["source_type"],
            source_path=entry.production_file.as_posix(),
            checksum=self._row_checksum(row),
            selection_key=selection_key,
        )

    def _validate_item_scope(self, row: dict[str, str], *, entry: CatalogManifestEntry) -> None:
        if row["theme_id"] != entry.theme_id:
            raise CatalogSourceError(
                f"Theme mismatch for {row['item_id']}: manifest={entry.theme_id}, row={row['theme_id']}",
            )
        if not row["item_id"]:
            raise CatalogSourceError("Catalog item row is missing item_id")
        if not row["version"]:
            raise CatalogSourceError(f"Catalog item {row['item_id']} is missing version")

    def _options(self, row: dict[str, str]) -> list[Any]:
        try:
            options = json.loads(row["options"])
        except json.JSONDecodeError:
            options = self._legacy_options(row)
        if not isinstance(options, list) or not options:
            raise CatalogSourceError(f"Options must be a non-empty list for {row['item_id']}")
        return options

    @staticmethod
    def _legacy_options(row: dict[str, str]) -> Any:
        try:
            return ast.literal_eval(row["options"])
        except (ValueError, SyntaxError) as exc:
            raise CatalogSourceError(f"Invalid options JSON for {row['item_id']}") from exc

    @staticmethod
    def _tags(row: dict[str, str]) -> list[str]:
        value = row.get("tags", "")
        return [part.strip() for part in value.split(";") if part.strip()]

    @staticmethod
    def _optional(row: dict[str, str], field: str) -> str | None:
        value = row.get(field, "").strip()
        return value or None

    @staticmethod
    def _int_field(row: dict[str, str], field: str) -> int:
        try:
            return int(row[field])
        except ValueError as exc:
            raise CatalogSourceError(f"Invalid integer field {field}: {row[field]!r}") from exc

    @staticmethod
    def _row_checksum(row: dict[str, str]) -> str:
        payload = json.dumps(row, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @staticmethod
    def _file_checksum(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    @staticmethod
    def _read_csv(path: Path, *, required_columns: set[str]) -> list[dict[str, str]]:
        if not path.exists():
            raise CatalogSourceError(f"CSV file does not exist: {path}")
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            missing = required_columns - set(reader.fieldnames or [])
            if missing:
                raise CatalogSourceError(f"CSV file {path} is missing columns: {sorted(missing)}")
            return [dict(row) for row in reader]
