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
        return await db.scalar(select(QuestionReference).where(QuestionReference.item_id == item_id))

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
        existing = await self.get_by_item_id(db, item_id)
        if existing is not None:
            existing.level = level
            existing.theme = theme
            existing.theme_key = theme_key
            existing.metadata_snapshot = metadata_snapshot
            existing.content_version = content_version
            existing.question_text_snapshot = question_text_snapshot
            existing.correct_answer_snapshot = correct_answer_snapshot
            existing.explanation_snapshot = explanation_snapshot
            existing.fetched_at = datetime.now(UTC)
            return existing

        question_reference = QuestionReference(
            id=await next_sqlite_id_if_needed(db, QuestionReference),
            item_id=item_id,
            level=level,
            theme=theme,
            theme_key=theme_key,
            metadata_snapshot=metadata_snapshot,
            content_version=content_version,
            question_text_snapshot=question_text_snapshot,
            correct_answer_snapshot=correct_answer_snapshot,
            explanation_snapshot=explanation_snapshot,
        )
        db.add(question_reference)
        return question_reference
