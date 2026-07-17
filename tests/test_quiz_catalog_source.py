from __future__ import annotations

from pathlib import Path

import pytest

from app.services.quiz_catalog_source import CatalogSourceError, QuizCatalogSourceReader


def test_source_reader_loads_manifest_and_items(tmp_path: Path) -> None:
    source_root = _write_source(
        tmp_path,
        manifest_count=2,
        rows=[
            _item_row("item-1", answer_key="1"),
            _item_row("item-2", answer_key="0", tags="theme:t04;level:a1"),
        ],
    )

    reader = QuizCatalogSourceReader(source_root)
    manifest = reader.read_manifest()
    items = reader.read_items(manifest[0])

    assert len(manifest) == 1
    assert manifest[0].production_file == Path("ProductionQuizBank/T04/T04_A1.csv")
    assert len(items) == 2
    assert items[0].item_id == "item-1"
    assert items[0].level == "A1"
    assert items[0].theme_id == "T04"
    assert items[0].selection_key == 1
    assert len(items[0].checksum) == 64
    assert items[1].tags == ["theme:t04", "level:a1"]
    assert len(reader.manifest_checksum()) == 64
    assert len(reader.file_checksum(manifest[0].production_file)) == 64


def test_source_reader_treats_manifest_count_as_metadata(tmp_path: Path) -> None:
    source_root = _write_source(tmp_path, manifest_count=2, rows=[_item_row("item-1")])

    reader = QuizCatalogSourceReader(source_root)
    manifest = reader.read_manifest()
    items = reader.read_items(manifest[0])

    assert manifest[0].item_count == 2
    assert len(items) == 1


def test_source_reader_rejects_invalid_options_json(tmp_path: Path) -> None:
    source_root = _write_source(tmp_path, manifest_count=1, rows=[_item_row("item-1", options="not-json")])

    reader = QuizCatalogSourceReader(source_root)
    manifest = reader.read_manifest()

    with pytest.raises(CatalogSourceError, match="Invalid options JSON"):
        reader.read_items(manifest[0])


def test_source_reader_rejects_single_option_rows(tmp_path: Path) -> None:
    source_root = _write_source(tmp_path, manifest_count=1, rows=[_item_row("item-1", options='["only one"]')])

    reader = QuizCatalogSourceReader(source_root)
    manifest = reader.read_manifest()

    with pytest.raises(CatalogSourceError, match="At least two usable options"):
        reader.read_items(manifest[0])


def test_source_reader_accepts_legacy_python_list_options(tmp_path: Path) -> None:
    source_root = _write_source(
        tmp_path,
        manifest_count=1,
        rows=[_item_row("item-1", options="['Feingefuehl', 'Vorsicht']")],
    )

    reader = QuizCatalogSourceReader(source_root)
    manifest = reader.read_manifest()
    items = reader.read_items(manifest[0])

    assert items[0].item_id == "item-1"


def test_source_reader_rejects_answer_key_outside_options(tmp_path: Path) -> None:
    source_root = _write_source(tmp_path, manifest_count=1, rows=[_item_row("item-1", answer_key="3")])

    reader = QuizCatalogSourceReader(source_root)
    manifest = reader.read_manifest()

    with pytest.raises(CatalogSourceError, match="Invalid answer_key"):
        reader.read_items(manifest[0])


def test_source_reader_rejects_theme_mismatch(tmp_path: Path) -> None:
    source_root = _write_source(tmp_path, manifest_count=1, rows=[_item_row("item-1", theme_id="T05")])

    reader = QuizCatalogSourceReader(source_root)
    manifest = reader.read_manifest()

    with pytest.raises(CatalogSourceError, match="Theme mismatch"):
        reader.read_items(manifest[0])


def test_source_reader_rejects_level_mismatch(tmp_path: Path) -> None:
    source_root = _write_source(tmp_path, manifest_count=1, rows=[_item_row("item-1", sublevel="B1")])

    reader = QuizCatalogSourceReader(source_root)
    manifest = reader.read_manifest()

    with pytest.raises(CatalogSourceError, match="Level mismatch"):
        reader.read_items(manifest[0])


def test_source_reader_rejects_manifest_path_traversal(tmp_path: Path) -> None:
    source_root = _write_source(tmp_path, manifest_count=1, rows=[_item_row("item-1")])
    _write_manifest(source_root, production_file="../outside.csv", manifest_count=1)

    reader = QuizCatalogSourceReader(source_root)
    manifest = reader.read_manifest()

    with pytest.raises(CatalogSourceError, match="escapes catalog root"):
        reader.read_items(manifest[0])


def test_source_reader_wraps_missing_numeric_cells(tmp_path: Path) -> None:
    source_root = tmp_path / "ProductionQuizBank"
    registry = source_root / "_registry"
    registry.mkdir(parents=True)
    (registry / "production_manifest.csv").write_text(
        "\n".join(
            [
                "production_file,theme_id,theme_slug,cefr_level,item_count,source_file_count,source_row_count",
                "ProductionQuizBank/T04/T04_A1.csv,T04,einkaufen_geld_konsum,A1,1,1",
            ],
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(CatalogSourceError, match="Missing integer field source_row_count"):
        QuizCatalogSourceReader(source_root).read_manifest()


def test_source_reader_requires_content_columns(tmp_path: Path) -> None:
    source_root = _write_source(tmp_path, manifest_count=1, rows=[_item_row("item-1")])
    item_file = source_root / "T04" / "T04_A1.csv"
    rows = [_item_row("item-1")]
    header = [column for column in rows[0] if column != "explanation"]
    item_file.write_text(_csv(rows, header=header), encoding="utf-8")

    reader = QuizCatalogSourceReader(source_root)
    manifest = reader.read_manifest()

    with pytest.raises(CatalogSourceError, match="missing columns"):
        reader.read_items(manifest[0])


def _write_source(tmp_path: Path, *, manifest_count: int, rows: list[dict[str, str]]) -> Path:
    source_root = tmp_path / "ProductionQuizBank"
    registry = source_root / "_registry"
    registry.mkdir(parents=True)
    item_dir = source_root / "T04"
    item_dir.mkdir()
    _write_manifest(source_root, production_file="ProductionQuizBank/T04/T04_A1.csv", manifest_count=manifest_count)
    item_file = item_dir / "T04_A1.csv"
    item_file.write_text(_csv(rows), encoding="utf-8")
    return source_root


def _write_manifest(source_root: Path, *, production_file: str, manifest_count: int) -> None:
    (source_root / "_registry" / "production_manifest.csv").write_text(
        "\n".join(
            [
                "production_file,theme_id,theme_slug,cefr_level,item_count,source_file_count,source_row_count",
                f"{production_file},T04,einkaufen_geld_konsum,A1,{manifest_count},1,{manifest_count}",
            ],
        )
        + "\n",
        encoding="utf-8",
    )


def _csv(rows: list[dict[str, str]], *, header: list[str] | None = None) -> str:
    header = header or list(_item_row("header").keys())
    lines = [",".join(header)]
    for row in rows:
        lines.append(",".join(_csv_value(row[column]) for column in header))
    return "\n".join(lines) + "\n"


def _csv_value(value: str) -> str:
    escaped = value.replace('"', '""')
    return f'"{escaped}"'


def _item_row(
    item_id: str,
    *,
    theme_id: str = "T04",
    sublevel: str = "A1",
    options: str = '["der", "die"]',
    answer_key: str = "0",
    tags: str = "legacy_file:test",
) -> dict[str, str]:
    return {
        "item_id": item_id,
        "language": "de",
        "level_band": "A1-A2",
        "sublevel": sublevel,
        "theme_id": theme_id,
        "subtheme_id": "einkauf",
        "objective_id": "O03",
        "pattern_id": "P02",
        "difficulty_band": "A1-A2",
        "register": "standard_neutral",
        "prompt": "Was passt?",
        "stem_text": "___ Rechnung ist hier.",
        "options": options,
        "answer_key": answer_key,
        "explanation": "Richtig ist die.",
        "tags": tags,
        "coverage_cell_id": "A1::T04::O03::P02",
        "status": "active",
        "version": "1.0",
        "source_type": "legacy_quizbank_migration",
        "provenance_note": "test",
        "created_at": "2026-02-14T18:51:00Z",
        "updated_at": "2026-02-14T18:51:00Z",
        "reviewed_at": "",
        "level_locked": "false",
        "locked_at": "",
    }
