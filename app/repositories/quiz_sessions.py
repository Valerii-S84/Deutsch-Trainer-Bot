from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import QuizSession


class QuizSessionStatus:
    active = "active"
    completed = "completed"
    cancelled = "cancelled"
    failed = "failed"


class QuizSessionRepository:
    """Data access helpers for training sessions."""

    async def get_active_for_user(self, db: AsyncSession, user_id: int) -> QuizSession | None:
        query = select(QuizSession).where(
            QuizSession.user_id == user_id,
            QuizSession.status == QuizSessionStatus.active,
        )
        return await db.scalar(query)

    async def get_by_id_for_user(
        self,
        db: AsyncSession,
        session_id: int,
        user_id: int,
    ) -> QuizSession | None:
        query = select(QuizSession).where(
            QuizSession.id == session_id,
            QuizSession.user_id == user_id,
        )
        return await db.scalar(query)

    async def create(
        self,
        db: AsyncSession,
        *,
        user_id: int,
        level: str,
        theme: str | None,
        total_questions: int,
        source: str,
        source_metadata: dict[str, Any] | None = None,
        api_metadata: dict[str, Any] | None = None,
    ) -> QuizSession:
        session = QuizSession(
            user_id=user_id,
            level=level,
            theme=theme,
            session_type=str((source_metadata or {}).get("flow") or "regular"),
            status=QuizSessionStatus.active,
            total_questions=total_questions,
            shown_questions_count=0,
            answered_count=0,
            correct_answers=0,
            source=source,
            source_metadata=source_metadata,
            api_metadata=api_metadata,
            started_at=datetime.now(UTC),
        )
        db.add(session)
        return session

    async def set_status(
        self,
        db: AsyncSession,
        session: QuizSession,
        status: str,
        *,
        finished_at: datetime | None = None,
    ) -> QuizSession:
        session.status = status
        if status in {QuizSessionStatus.completed, QuizSessionStatus.cancelled, QuizSessionStatus.failed}:
            session.finished_at = finished_at or datetime.now(UTC)
        if status == QuizSessionStatus.completed:
            session.completed_at = session.finished_at
        elif status == QuizSessionStatus.cancelled:
            session.abandoned_at = session.finished_at
        elif status == QuizSessionStatus.failed:
            session.failed_at = session.finished_at
        return session

    async def mark_completed(self, db: AsyncSession, session: QuizSession, *, finished_at: datetime | None = None) -> QuizSession:
        return await self.set_status(db, session, QuizSessionStatus.completed, finished_at=finished_at)

    async def mark_cancelled(self, db: AsyncSession, session: QuizSession, *, finished_at: datetime | None = None) -> QuizSession:
        return await self.set_status(db, session, QuizSessionStatus.cancelled, finished_at=finished_at)

    async def mark_failed(self, db: AsyncSession, session: QuizSession, *, finished_at: datetime | None = None) -> QuizSession:
        return await self.set_status(db, session, QuizSessionStatus.failed, finished_at=finished_at)

    async def set_pending_question(
        self,
        db: AsyncSession,
        session: QuizSession,
        question_data: dict[str, Any],
    ) -> QuizSession:
        current_metadata = dict(session.api_metadata or {})
        current_metadata["pending_question"] = question_data
        session.api_metadata = current_metadata
        return session

    async def clear_pending_question(self, db: AsyncSession, session: QuizSession) -> QuizSession:
        metadata = dict(session.api_metadata or {})
        metadata.pop("pending_question", None)
        session.api_metadata = metadata
        return session

    async def set_api_metadata(self, db: AsyncSession, session: QuizSession, api_metadata: dict[str, Any] | None) -> QuizSession:
        session.api_metadata = api_metadata
        return session

    async def increment_correct_answers(self, db: AsyncSession, session: QuizSession, delta: int) -> int:
        session.correct_answers = (session.correct_answers or 0) + delta
        return session.correct_answers

    async def increment_answered_count(self, db: AsyncSession, session: QuizSession, delta: int) -> int:
        session.answered_count = int(getattr(session, "answered_count", 0) or 0) + delta
        return session.answered_count
