from __future__ import annotations

from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Progress


class ProgressRepository:
    """Persistence helpers for user progress aggregation."""

    async def get_by_user_level_theme(
        self,
        db: AsyncSession,
        *,
        user_id: int,
        level: str,
        theme: str | None,
    ) -> Progress | None:
        query = select(Progress).where(
            and_(
                Progress.user_id == user_id,
                Progress.level == level,
                Progress.theme == theme,
            ),
        )
        return await db.scalar(query)

    async def create(
        self,
        db: AsyncSession,
        *,
        user_id: int,
        level: str,
        theme: str | None,
    ) -> Progress:
        progress_id = await self._next_id_if_needed(db)
        progress = Progress(
            id=progress_id,
            user_id=user_id,
            level=level,
            theme=theme,
            total_answered=0,
            total_correct=0,
            wrong_count=0,
            accuracy=Decimal("0.00"),
            stability_score=Decimal("0.00"),
            weakness_score=Decimal("0.00"),
        )
        db.add(progress)
        return progress

    async def _next_id_if_needed(self, db: AsyncSession) -> int | None:
        if db.get_bind().dialect.name != "sqlite":
            return None
        max_id = await db.scalar(select(func.max(Progress.id)))
        return (max_id or 0) + 1

    async def get_or_create(
        self,
        db: AsyncSession,
        *,
        user_id: int,
        level: str,
        theme: str | None,
    ) -> Progress:
        existing = await self.get_by_user_level_theme(db, user_id=user_id, level=level, theme=theme)
        if existing is not None:
            return existing
        return await self.create(db, user_id=user_id, level=level, theme=theme)

    async def update_totals(
        self,
        _db: AsyncSession,
        progress: Progress,
        *,
        answered_delta: int,
        correct_delta: int,
    ) -> Progress:
        deltas = self._normalize_deltas(answered_delta=answered_delta, correct_delta=correct_delta)
        progress.total_answered = max(0, (progress.total_answered or 0) + deltas["answered_delta"])
        progress.total_correct = max(
            0,
            min(
                progress.total_answered,
                (progress.total_correct or 0) + deltas["correct_delta"],
            ),
        )
        wrong_delta = max(0, deltas["answered_delta"] - deltas["correct_delta"])
        if hasattr(progress, "wrong_count"):
            progress.wrong_count = max(0, (progress.wrong_count or 0) + wrong_delta)

        if progress.total_answered <= 0:
            progress.accuracy = Decimal("0.00")
        else:
            raw_accuracy = (Decimal(progress.total_correct) * Decimal("100")) / Decimal(progress.total_answered)
            progress.accuracy = raw_accuracy.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        if hasattr(progress, "last_answered_at"):
            progress.last_answered_at = datetime.now(UTC)
        if hasattr(progress, "last_wrong_at") and wrong_delta:
            progress.last_wrong_at = progress.last_answered_at
        if hasattr(progress, "last_recalculated_at"):
            progress.last_recalculated_at = datetime.now(UTC)
        return progress

    async def update_streak_if_supported(self, progress: Progress, *, is_correct: bool) -> Progress:
        if not hasattr(progress, "streak"):
            return progress

        current_streak = int(progress.streak or 0)
        progress.streak = current_streak + 1 if is_correct else 0
        return progress

    async def get_user_summary(self, db: AsyncSession, *, user_id: int) -> list[Progress]:
        query = (
            select(Progress)
            .where(Progress.user_id == user_id)
            .order_by(Progress.level.asc(), Progress.theme.asc())
        )
        result = await db.execute(query)
        return list(result.scalars().all())

    async def get_level_theme_summary(
        self,
        db: AsyncSession,
        *,
        user_id: int,
        level: str | None = None,
        theme: str | None = None,
    ) -> list[Progress]:
        query = select(Progress).where(Progress.user_id == user_id)
        if level is not None:
            query = query.where(Progress.level == level)
        if theme is not None:
            query = query.where(Progress.theme == theme)

        query = query.order_by(Progress.level.asc(), Progress.theme.asc())
        result = await db.execute(query)
        return list(result.scalars().all())

    @staticmethod
    def _normalize_deltas(*, answered_delta: int, correct_delta: int) -> dict[str, int]:
        return {
            "answered_delta": max(0, answered_delta),
            "correct_delta": max(0, correct_delta),
        }
