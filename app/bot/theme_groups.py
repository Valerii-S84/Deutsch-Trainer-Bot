"""Static UX grouping for local catalog theme ids."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ThemeGroup:
    group_id: str
    label: str
    theme_ids: tuple[str, ...]


THEME_GROUPS: tuple[ThemeGroup, ...] = (
    ThemeGroup("G01", "Ich & Alltag", ("T01", "T02", "T05")),
    ThemeGroup("G02", "Wohnen & Erledigungen", ("T03", "T04", "T10")),
    ThemeGroup("G03", "Arbeit & Lernen", ("T06", "T07", "T15")),
    ThemeGroup("G04", "Unterwegs & Kontakte", ("T08", "T09", "T11")),
    ThemeGroup("G05", "Gesellschaft & Umwelt", ("T13", "T14", "T17")),
    ThemeGroup("G06", "Medien & Wissen", ("T12", "T16", "T18")),
)

THEME_IDS: frozenset[str] = frozenset(
    theme_id
    for group in THEME_GROUPS
    for theme_id in group.theme_ids
)


def is_known_theme_id(value: str | None) -> bool:
    return (value or "").strip().upper() in THEME_IDS


def normalize_theme_id(value: str | None) -> str:
    theme_id = (value or "").strip().upper()
    if theme_id not in THEME_IDS:
        raise ValueError("unknown theme id")
    return theme_id


def get_theme_group(group_id: str | None) -> ThemeGroup | None:
    normalized = (group_id or "").strip().upper()
    return next((group for group in THEME_GROUPS if group.group_id == normalized), None)
