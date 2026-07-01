from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import QuestionReference
from app.repositories.sqlite_compat import next_sqlite_id_if_needed


class QuestionReferenceRepository:
    """Persistence for minimal Quiz Bank item references."""

    async def get_by_item_id(self, db: AsyncSession, item_id: str) -> QuestionReference | None:
        return await db.scalar(
            select(QuestionReference).where(
                QuestionReference.item_id == item_id,
                QuestionReference.catalog_id.is_(None),
                QuestionReference.item_version.is_(None),
            ),
        )

    async def get_by_catalog_item(
        self,
        db: AsyncSession,
        *,
        catalog_id: str,
        item_id: str,
        item_version: str | None,
    ) -> QuestionReference | None:
        query = select(QuestionReference).where(
            QuestionReference.catalog_id == catalog_id,
            QuestionReference.item_id == item_id,
            QuestionReference.item_version == item_version,
        )
        return await db.scalar(query)

    async def upsert_snapshot(
        self,
        db: AsyncSession,
        *,
        item_id: str,
        level: str,
        theme: str,
        theme_key: str | None,
        metadata_snapshot: dict[str, Any] | None,
        content_version: str | None,
        question_text_snapshot: str | None,
        correct_answer_snapshot: str | None,
        explanation_snapshot: str | None,
    ) -> QuestionReference:
        catalog_id = _catalog_id_from_metadata(metadata_snapshot)
        item_version = _item_version_from_metadata(metadata_snapshot, content_version)
        if catalog_id:
            existing = await self.get_by_catalog_item(
                db,
                catalog_id=catalog_id,
                item_id=item_id,
                item_version=item_version,
            )
        else:
            existing = await self.get_by_item_id(db, item_id)
        if existing is not None:
            existing.catalog_id = catalog_id
            existing.item_version = item_version
            existing.level = level
            existing.theme = theme
            existing.theme_key = theme_key
            existing.source = "local_quiz_catalog" if catalog_id else existing.source
            existing.metadata_snapshot = metadata_snapshot
            existing.content_version = content_version
            existing.question_text_snapshot = question_text_snapshot
            existing.correct_answer_snapshot = correct_answer_snapshot
            existing.explanation_snapshot = explanation_snapshot
            existing.fetched_at = datetime.now(UTC)
            return existing

        question_reference = QuestionReference(
            id=await next_sqlite_id_if_needed(db, QuestionReference),
            catalog_id=catalog_id,
            item_id=item_id,
            item_version=item_version,
            level=level,
            theme=theme,
            theme_key=theme_key,
            source="local_quiz_catalog" if catalog_id else "quiz_bank_api",
            metadata_snapshot=metadata_snapshot,
            content_version=content_version,
            question_text_snapshot=question_text_snapshot,
            correct_answer_snapshot=correct_answer_snapshot,
            explanation_snapshot=explanation_snapshot,
        )
        db.add(question_reference)
        return question_reference


def _catalog_id_from_metadata(metadata: dict[str, Any] | None) -> str | None:
    value = (metadata or {}).get("catalog_id")
    return value if isinstance(value, str) and value else None


def _item_version_from_metadata(metadata: dict[str, Any] | None, fallback: str | None) -> str | None:
    value = (metadata or {}).get("item_version")
    if isinstance(value, str) and value:
        return value
    return fallback
