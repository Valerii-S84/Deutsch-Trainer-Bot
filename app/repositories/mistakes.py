from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Mistake, MistakeStatus


class MistakeRepository:
    """Persistence helpers for mistake capture and review lifecycle."""

    async def find_active_by_user_and_external_quiz_id(
        self,
        db: AsyncSession,
        *,
        user_id: int,
        external_quiz_id: str,
    ) -> Mistake | None:
        query = (
            select(Mistake)
            .where(
                Mistake.user_id == user_id,
                Mistake.external_quiz_id == external_quiz_id,
                Mistake.resolved_at.is_(None),
            )
            .order_by(Mistake.id.desc())
        )
        return await db.scalar(query)

    async def get_active_by_user_and_external_quiz_id(
        self,
        db: AsyncSession,
        *,
        user_id: int,
        external_quiz_id: str,
    ) -> Mistake | None:
        return await self.find_active_by_user_and_external_quiz_id(
            db,
            user_id=user_id,
            external_quiz_id=external_quiz_id,
        )

    async def get_by_user_and_external_quiz_id(
        self,
        db: AsyncSession,
        *,
        user_id: int,
        external_quiz_id: str,
        active_only: bool = False,
    ) -> Mistake | None:
        query = select(Mistake).where(
            Mistake.user_id == user_id,
            Mistake.external_quiz_id == external_quiz_id,
        )
        if active_only:
            query = query.where(Mistake.resolved_at.is_(None))
        query = query.order_by(Mistake.id.desc())
        return await db.scalar(query)

    async def create(
        self,
        db: AsyncSession,
        *,
        user_id: int,
        external_quiz_id: str,
        level: str,
        theme: str,
        wrong_answer: str,
        correct_answer: str,
        source_snapshot: dict[str, Any] | None = None,
    ) -> Mistake:
        mistake = Mistake(
            user_id=user_id,
            external_quiz_id=external_quiz_id,
            level=level,
            theme=theme,
            wrong_answer=wrong_answer,
            correct_answer=correct_answer,
            mistake_count=1,
            last_seen_at=datetime.now(UTC),
            status=MistakeStatus.new,
            source_snapshot=source_snapshot,
        )
        db.add(mistake)
        return mistake

    async def increment_wrong(
        self,
        db: AsyncSession,
        mistake: Mistake,
        *,
        wrong_answer: str,
        correct_answer: str,
        source_snapshot: dict[str, Any] | None = None,
    ) -> Mistake:
        mistake.mistake_count = int(max(0, mistake.mistake_count or 0)) + 1
        mistake.wrong_answer = wrong_answer
        mistake.correct_answer = correct_answer
        if source_snapshot is not None:
            mistake.source_snapshot = source_snapshot
        mistake.status = MistakeStatus.repeated if mistake.status in {
            MistakeStatus.new,
            MistakeStatus.repeated,
            MistakeStatus.improved,
        } else mistake.status
        mistake.resolved_at = None
        mistake.last_seen_at = datetime.now(UTC)
        return mistake

    async def resolve(
        self,
        db: AsyncSession,
        mistake: Mistake,
    ) -> Mistake:
        mistake.status = MistakeStatus.resolved
        mistake.resolved_at = datetime.now(UTC)
        return mistake

    async def reopen_as_active(
        self,
        db: AsyncSession,
        mistake: Mistake,
        *,
        wrong_answer: str,
        correct_answer: str,
        source_snapshot: dict[str, Any] | None = None,
    ) -> Mistake:
        mistake.status = MistakeStatus.repeated
        mistake.mistake_count = max(1, int(mistake.mistake_count or 0) + 1)
        mistake.resolved_at = None
        mistake.last_seen_at = datetime.now(UTC)
        mistake.wrong_answer = wrong_answer
        mistake.correct_answer = correct_answer
        if source_snapshot is not None:
            mistake.source_snapshot = source_snapshot
        return mistake

    async def list_active_for_user(self, db: AsyncSession, *, user_id: int) -> list[Mistake]:
        query = (
            select(Mistake)
            .where(Mistake.user_id == user_id, Mistake.resolved_at.is_(None))
            .order_by(Mistake.last_seen_at.desc(), Mistake.id.asc())
        )
        result = await db.execute(query)
        return list(result.scalars().all())

    async def get_weak_area_summary(
        self,
        db: AsyncSession,
        *,
        user_id: int,
    ) -> list[dict[str, object]]:
        query = (
            select(
                Mistake.level.label("level"),
                Mistake.theme.label("theme"),
                func.coalesce(func.sum(Mistake.mistake_count), 0).label("mistake_count"),
            )
            .where(Mistake.user_id == user_id, Mistake.resolved_at.is_(None))
            .group_by(Mistake.level, Mistake.theme)
            .order_by(Mistake.level.asc(), Mistake.theme.asc())
        )

        rows = (await db.execute(query)).all()
        return [
            {
                "level": row.level,
                "theme": row.theme,
                "mistake_count": int(row.mistake_count),
            }
            for row in rows
        ]
