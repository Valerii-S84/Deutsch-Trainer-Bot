from __future__ import annotations

from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Mistake, Progress, UserAnswer
from app.repositories.sqlite_compat import next_sqlite_id_if_needed
from app.services.progress_model import TopicAnswerEvent, TopicMistakeSignals, TopicScores


class _ProgressWriteRepository:
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
        progress_id = await next_sqlite_id_if_needed(db, Progress)
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

    async def create_from_answer(
        self,
        db: AsyncSession,
        *,
        user_id: int,
        level: str,
        theme: str | None,
        theme_key: str | None,
        is_correct: bool,
        now: datetime,
    ) -> Progress:
        progress_id = await next_sqlite_id_if_needed(db, Progress)
        total_correct = 1 if is_correct else 0
        wrong_count = 0 if is_correct else 1
        progress = Progress(
            id=progress_id,
            user_id=user_id,
            level=level,
            theme=theme,
            theme_key=theme_key,
            total_answered=1,
            total_correct=total_correct,
            wrong_count=wrong_count,
            accuracy=Decimal("100.00") if is_correct else Decimal("0.00"),
            stability_score=Decimal("0.00"),
            weakness_score=Decimal("0.00"),
            streak=1 if is_correct else 0,
            last_answered_at=now,
            last_wrong_at=None if is_correct else now,
            last_recalculated_at=now,
        )
        db.add(progress)
        return progress

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
        now: datetime | None = None,
    ) -> Progress:
        update_time = now or datetime.now(UTC)
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
            progress.last_answered_at = update_time
        if hasattr(progress, "last_wrong_at") and wrong_delta:
            progress.last_wrong_at = progress.last_answered_at
        if hasattr(progress, "last_recalculated_at"):
            progress.last_recalculated_at = update_time
        return progress

    async def apply_topic_scores(
        self,
        _db: AsyncSession,
        progress: Progress,
        *,
        scores: TopicScores,
        unique_items_seen: int,
        available_items_count: int | None,
        theme_key: str | None,
        now: datetime | None = None,
    ) -> Progress:
        progress.unique_items_seen = max(0, unique_items_seen)
        progress.available_items_count = available_items_count
        progress.coverage_score = scores.coverage_score
        progress.coverage_status = scores.coverage_status
        progress.stability_score = scores.stability_score
        progress.weakness_score = scores.weakness_score
        progress.recency_score = scores.recency_score
        progress.topic_status = scores.topic_status
        if theme_key:
            progress.theme_key = theme_key
        if hasattr(progress, "last_recalculated_at"):
            progress.last_recalculated_at = now or datetime.now(UTC)
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

class ProgressRepository(_ProgressWriteRepository):
    async def list_topic_answer_events(
        self,
        db: AsyncSession,
        *,
        user_id: int,
        level: str,
        theme: str | None,
    ) -> list[TopicAnswerEvent]:
        query = select(
            UserAnswer.external_quiz_id,
            UserAnswer.is_correct,
            UserAnswer.answered_at,
            UserAnswer.session_type,
        ).where(
            UserAnswer.user_id == user_id,
            UserAnswer.level == level,
        )
        if theme is None:
            query = query.where(UserAnswer.theme.is_(None))
        else:
            query = query.where(UserAnswer.theme == theme)

        query = query.order_by(UserAnswer.answered_at.asc(), UserAnswer.id.asc())
        rows = (await db.execute(query)).all()
        return [
            TopicAnswerEvent(
                item_id=str(row.external_quiz_id),
                is_correct=bool(row.is_correct),
                answered_at=row.answered_at,
                session_type=row.session_type,
            )
            for row in rows
        ]

    async def list_recent_topic_answer_events(
        self,
        db: AsyncSession,
        *,
        user_id: int,
        level: str,
        theme: str | None,
        limit: int,
    ) -> list[TopicAnswerEvent]:
        query = select(
            UserAnswer.external_quiz_id,
            UserAnswer.is_correct,
            UserAnswer.answered_at,
            UserAnswer.session_type,
        ).where(
            UserAnswer.user_id == user_id,
            UserAnswer.level == level,
        )
        if theme is None:
            query = query.where(UserAnswer.theme.is_(None))
        else:
            query = query.where(UserAnswer.theme == theme)

        query = query.order_by(UserAnswer.answered_at.desc(), UserAnswer.id.desc()).limit(limit)
        rows = (await db.execute(query)).all()
        events = [
            TopicAnswerEvent(
                item_id=str(row.external_quiz_id),
                is_correct=bool(row.is_correct),
                answered_at=row.answered_at,
                session_type=row.session_type,
            )
            for row in rows
        ]
        return sorted(events, key=lambda item: item.answered_at)

    async def has_topic_item_answer(
        self,
        db: AsyncSession,
        *,
        user_id: int,
        level: str,
        theme: str | None,
        item_id: str,
        exclude_user_answer_id: int | None = None,
    ) -> bool:
        query = select(UserAnswer.id).where(
            UserAnswer.user_id == user_id,
            UserAnswer.level == level,
            UserAnswer.external_quiz_id == item_id,
        )
        if theme is None:
            query = query.where(UserAnswer.theme.is_(None))
        else:
            query = query.where(UserAnswer.theme == theme)
        if exclude_user_answer_id is not None:
            query = query.where(UserAnswer.id != exclude_user_answer_id)
        query = query.limit(1)
        return await db.scalar(query) is not None

    async def get_topic_mistake_signals(
        self,
        db: AsyncSession,
        *,
        user_id: int,
        level: str,
        theme: str | None,
    ) -> TopicMistakeSignals:
        query = select(
            Mistake.item_id,
            Mistake.external_quiz_id,
            Mistake.mistake_count,
        ).where(
            Mistake.user_id == user_id,
            Mistake.level == level,
            Mistake.resolved_at.is_(None),
        )
        if theme is None:
            query = query.where(Mistake.theme.is_(None))
        else:
            query = query.where(Mistake.theme == theme)

        rows = (await db.execute(query)).all()
        unresolved_item_ids = frozenset(str(row.item_id or row.external_quiz_id) for row in rows)
        total_mistake_count = sum(max(0, int(row.mistake_count or 0)) for row in rows)
        repeated_mistake_count = sum(max(0, int(row.mistake_count or 0) - 1) for row in rows)
        return TopicMistakeSignals(
            unresolved_count=len(rows),
            total_mistake_count=total_mistake_count,
            repeated_mistake_count=repeated_mistake_count,
            unresolved_item_ids=unresolved_item_ids,
        )

    @staticmethod
    def _normalize_deltas(*, answered_delta: int, correct_delta: int) -> dict[str, int]:
        return {
            "answered_delta": max(0, answered_delta),
            "correct_delta": max(0, correct_delta),
        }
