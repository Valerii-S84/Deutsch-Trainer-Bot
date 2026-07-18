from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.catalog.selection import CatalogQuestionRequest, LocalCatalogQuestion, LocalCatalogSelector
from app.config import Settings, get_settings
from app.db.models import QuizCatalog, QuizCatalogItem
from app.quiz_bank.schemas import (
    QuizAnswerOption,
    QuizAvailabilityResponse,
    QuizCorrectAnswerReference,
    QuizItem,
    QuizQuestionsResponse,
    QuizQuestionExplanation,
    QuizSourceMetadata,
    QuizTheme,
    QuizThemesResponse,
)


class LocalCatalogNotConfiguredError(RuntimeError):
    """Raised when gameplay starts without an active local catalog."""


class LocalCatalogQuizService:
    """Quiz runtime source backed by the local PostgreSQL catalog."""

    def __init__(
        self,
        settings: Settings | None = None,
        selector: LocalCatalogSelector | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._selector = selector or LocalCatalogSelector(enabled_levels=self._settings.enabled_cefr_levels)

    async def request_quiz(
        self,
        db: AsyncSession,
        *,
        catalog_id: str | None = None,
        level: str,
        theme: str | None,
        limit: int = 1,
        user_context: Any | None = None,
        seed_material: str,
    ) -> QuizQuestionsResponse:
        if limit != 1:
            raise ValueError("Local Catalog gameplay currently selects one question at a time")
        active_catalog_id = self._catalog_id(catalog_id)
        excluded = tuple(_excluded_item_ids(user_context))
        question = await self._selector.next_question(
            db,
            CatalogQuestionRequest(
                catalog_id=active_catalog_id,
                seed_material=seed_material,
                level=level,
                theme_id=theme,
                excluded_item_ids=excluded,
            ),
        )
        items = [] if question is None else [self._to_quiz_item(question)]
        return QuizQuestionsResponse(items=items, requested_count=limit, returned_count=len(items), has_more=False)

    async def get_themes(
        self,
        db: AsyncSession,
        *,
        level: str,
        catalog_id: str | None = None,
    ) -> QuizThemesResponse:
        active_catalog_id = self._catalog_id(catalog_id)
        themes = await self._selector.list_themes(db, catalog_id=active_catalog_id, level=level)
        return QuizThemesResponse(
            level=level,
            themes=[
                QuizTheme(
                    theme=theme.theme_slug or theme.theme_id,
                    theme_key=theme.theme_id,
                    is_active=True,
                    available_items_count=theme.item_count,
                    metadata={"catalog_id": active_catalog_id},
                )
                for theme in themes
            ],
            content_version=await self.catalog_version(db, catalog_id=active_catalog_id),
        )

    async def get_availability(
        self,
        db: AsyncSession,
        *,
        level: str,
        theme: str,
        catalog_id: str | None = None,
    ) -> QuizAvailabilityResponse:
        active_catalog_id = self._catalog_id(catalog_id)
        count = await self._available_count(db, catalog_id=active_catalog_id, level=level, theme=theme)
        return QuizAvailabilityResponse(
            level=level,
            theme=theme,
            theme_key=theme,
            available_items_count=count,
            active_items_count=count,
            inactive_items_count=0,
            generated_at=datetime.now(UTC),
            content_version=await self.catalog_version(db, catalog_id=active_catalog_id),
        )

    async def catalog_version(self, db: AsyncSession, *, catalog_id: str | None = None) -> str | None:
        active_catalog_id = self._catalog_id(catalog_id)
        statement = select(QuizCatalog.catalog_version).where(QuizCatalog.catalog_id == active_catalog_id)
        return await db.scalar(statement)

    async def _available_count(self, db: AsyncSession, *, catalog_id: str, level: str, theme: str) -> int:
        statement = (
            select(func.count())
            .select_from(QuizCatalogItem)
            .where(QuizCatalogItem.catalog_id == catalog_id)
            .where(QuizCatalogItem.language == "de")
            .where(QuizCatalogItem.level == level.upper())
            .where(or_(QuizCatalogItem.theme_id == theme, QuizCatalogItem.theme_slug == theme))
            .where(QuizCatalogItem.status.in_(self._selector.selectable_statuses))
            .where(QuizCatalogItem.is_active.is_(True))
        )
        return int((await db.scalar(statement)) or 0)

    def _catalog_id(self, value: str | None = None) -> str:
        catalog_id = (value or self._settings.active_catalog_id or "").strip()
        if not catalog_id:
            raise LocalCatalogNotConfiguredError("ACTIVE_CATALOG_ID is required for Local Catalog gameplay")
        return catalog_id

    def _to_quiz_item(self, question: LocalCatalogQuestion) -> QuizItem:
        theme_key = question.theme_id
        metadata = dict(question.metadata or {})
        metadata.update(
            {
                "catalog_id": question.catalog_id,
                "item_version": question.item_version,
                "progress_theme_key": question.theme_slug or theme_key,
            },
        )
        return QuizItem(
            item_id=question.item_id,
            level=question.level,
            theme=question.theme_slug or theme_key,
            theme_key=theme_key,
            question_text=question.stem_text,
            answer_options=_answer_options(question.options),
            correct_answer=QuizCorrectAnswerReference(option_id=question.answer_key),
            explanation=QuizQuestionExplanation(text=question.explanation or "Keine Erklärung verfügbar."),
            metadata=metadata,
            content_version=question.item_version,
            source_metadata=QuizSourceMetadata(source="local_quiz_catalog", source_metadata=metadata),
        )


def _answer_options(options: list[object]) -> list[QuizAnswerOption]:
    return [
        QuizAnswerOption(option_id=str(index), text=str(text), order=index + 1)
        for index, text in enumerate(options)
    ]


def _excluded_item_ids(user_context: Any | None) -> list[str]:
    if user_context is None:
        return []
    if hasattr(user_context, "exclude_item_ids") and user_context.exclude_item_ids:
        return list(user_context.exclude_item_ids)
    if hasattr(user_context, "seen_item_ids") and user_context.seen_item_ids:
        return list(user_context.seen_item_ids)
    return []
