from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import TrainingSessionItem


class TrainingSessionItemStatus:
    prepared = "prepared"
    shown = "shown"
    answered = "answered"
    skipped = "skipped"
    invalid = "invalid"


class TrainingSessionItemRepository:
    """Persistence for per-session question item lifecycle."""

    async def get_by_session_item(
        self,
        db: AsyncSession,
        *,
        session_id: int,
        item_id: str,
    ) -> TrainingSessionItem | None:
        query = select(TrainingSessionItem).where(
            TrainingSessionItem.session_id == session_id,
            TrainingSessionItem.item_id == item_id,
        )
        return await db.scalar(query)

    async def create_shown(
        self,
        db: AsyncSession,
        *,
        session_id: int,
        user_id: int,
        question_reference_id: int,
        item_id: str,
        position: int,
    ) -> TrainingSessionItem:
        existing = await self.get_by_session_item(db, session_id=session_id, item_id=item_id)
        if existing is not None:
            existing.status = TrainingSessionItemStatus.shown
            existing.shown_at = existing.shown_at or datetime.now(UTC)
            return existing

        session_item = TrainingSessionItem(
            id=await self._next_id_if_needed(db),
            session_id=session_id,
            user_id=user_id,
            question_reference_id=question_reference_id,
            item_id=item_id,
            position=position,
            status=TrainingSessionItemStatus.shown,
            shown_at=datetime.now(UTC),
        )
        db.add(session_item)
        return session_item

    async def mark_daily_limit_charged(
        self,
        _db: AsyncSession,
        session_item: TrainingSessionItem,
        *,
        daily_limit_id: int | None = None,
    ) -> TrainingSessionItem:
        if session_item.shown_at is None:
            raise ValueError("Daily limit can only be charged after an item is shown")
        if session_item.daily_limit_charged_at is None:
            session_item.daily_limit_charged_at = datetime.now(UTC)
        if daily_limit_id is not None:
            session_item.daily_limit_id = daily_limit_id
        return session_item

    async def mark_answered(self, _db: AsyncSession, session_item: TrainingSessionItem) -> TrainingSessionItem:
        session_item.status = TrainingSessionItemStatus.answered
        session_item.answered_at = datetime.now(UTC)
        return session_item

    async def _next_id_if_needed(self, db: AsyncSession) -> int | None:
        if db.get_bind().dialect.name != "sqlite":
            return None
        max_id = await db.scalar(select(func.max(TrainingSessionItem.id)))
        return (max_id or 0) + 1
