from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Sequence

from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.catalog.checksums import selection_key_from_checksum
from app.db.models import QuizCatalogItem


DEFAULT_ENABLED_LEVELS = ("A1", "A2", "B1", "B2", "C1")
DEFAULT_SELECTABLE_STATUSES = ("reviewed", "active", "published")


@dataclass(frozen=True)
class CatalogQuestionRequest:
    catalog_id: str
    seed_material: str
    language: str = "de"
    level: str | None = None
    sublevel: str | None = None
    theme_id: str | None = None
    excluded_item_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class LocalCatalogQuestion:
    catalog_id: str
    item_id: str
    item_version: str
    language: str
    level: str
    sublevel: str | None
    theme_id: str
    theme_slug: str | None
    prompt: str | None
    stem_text: str
    options: list[object]
    answer_key: str
    explanation: str | None
    metadata: dict[str, object] | None


@dataclass(frozen=True)
class LocalCatalogTheme:
    theme_id: str
    theme_slug: str | None
    item_count: int


class CatalogLevelDisabledError(ValueError):
    """Raised when runtime config disables a stored catalog level."""


class LocalCatalogSelector:
    def __init__(
        self,
        *,
        enabled_levels: Sequence[str] = DEFAULT_ENABLED_LEVELS,
        selectable_statuses: Sequence[str] = DEFAULT_SELECTABLE_STATUSES,
    ) -> None:
        self.enabled_levels = tuple(level.upper() for level in enabled_levels)
        self.selectable_statuses = tuple(status.lower() for status in selectable_statuses)

    async def next_question(self, db: AsyncSession, request: CatalogQuestionRequest) -> LocalCatalogQuestion | None:
        self._ensure_enabled(request.level or request.sublevel)
        threshold = selection_key_for_seed(request.seed_material)
        base = self._base_query(request)
        result = await db.execute(self._seek_query(base, threshold, wrap=False))
        item = result.scalar_one_or_none()
        if item is None:
            result = await db.execute(self._seek_query(base, threshold, wrap=True))
            item = result.scalar_one_or_none()
        return None if item is None else self._to_question(item)

    async def list_themes(
        self,
        db: AsyncSession,
        *,
        catalog_id: str,
        language: str = "de",
        level: str | None = None,
    ) -> list[LocalCatalogTheme]:
        self._ensure_enabled(level)
        statement = (
            select(QuizCatalogItem.theme_id, QuizCatalogItem.theme_slug, func.count())
            .where(QuizCatalogItem.catalog_id == catalog_id)
            .where(QuizCatalogItem.language == language)
            .where(QuizCatalogItem.status.in_(self.selectable_statuses))
            .where(QuizCatalogItem.is_active.is_(True))
            .group_by(QuizCatalogItem.theme_id, QuizCatalogItem.theme_slug)
            .order_by(QuizCatalogItem.theme_id)
        )
        if level:
            statement = statement.where(QuizCatalogItem.level == level.upper())
        rows = await db.execute(statement)
        return [LocalCatalogTheme(row[0], row[1], int(row[2])) for row in rows.all()]

    def _base_query(self, request: CatalogQuestionRequest) -> Select[tuple[QuizCatalogItem]]:
        statement = (
            select(QuizCatalogItem)
            .where(QuizCatalogItem.catalog_id == request.catalog_id)
            .where(QuizCatalogItem.language == request.language)
            .where(QuizCatalogItem.status.in_(self.selectable_statuses))
            .where(QuizCatalogItem.is_active.is_(True))
        )
        if request.level:
            statement = statement.where(QuizCatalogItem.level == request.level.upper())
        if request.sublevel:
            statement = statement.where(QuizCatalogItem.sublevel == request.sublevel.upper())
        if request.theme_id:
            statement = statement.where(
                or_(
                    QuizCatalogItem.theme_id == request.theme_id,
                    QuizCatalogItem.theme_slug == request.theme_id,
                ),
            )
        if request.excluded_item_ids:
            statement = statement.where(QuizCatalogItem.item_id.notin_(request.excluded_item_ids))
        return statement

    def _seek_query(
        self,
        statement: Select[tuple[QuizCatalogItem]],
        threshold: int,
        *,
        wrap: bool,
    ) -> Select[tuple[QuizCatalogItem]]:
        comparator = QuizCatalogItem.selection_key < threshold if wrap else QuizCatalogItem.selection_key >= threshold
        return statement.where(comparator).order_by(QuizCatalogItem.selection_key).limit(1)

    def _ensure_enabled(self, level: str | None) -> None:
        if level and level.upper() not in self.enabled_levels:
            raise CatalogLevelDisabledError(f"CEFR level {level.upper()} is not enabled for runtime selection")

    def _to_question(self, item: QuizCatalogItem) -> LocalCatalogQuestion:
        return LocalCatalogQuestion(
            catalog_id=item.catalog_id,
            item_id=item.item_id,
            item_version=item.item_version,
            language=item.language,
            level=item.level,
            sublevel=item.sublevel,
            theme_id=item.theme_id,
            theme_slug=item.theme_slug,
            prompt=item.prompt,
            stem_text=item.stem_text,
            options=list(item.options),
            answer_key=item.answer_key,
            explanation=item.explanation,
            metadata=item.item_metadata,
        )


def selection_key_for_seed(seed_material: str) -> int:
    checksum = hashlib.sha256(seed_material.encode("utf-8")).hexdigest()
    return selection_key_from_checksum(checksum)
