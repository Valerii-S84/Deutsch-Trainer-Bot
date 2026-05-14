from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.entitlements import FEATURE_MISTAKE_REPEAT
from app.services.training_payloads import (
    ActiveSessionConflictError,
    NoReviewItemsError,
    QuizQuestionPayload,
)


class TrainingSessionLifecycleMixin:
    """Session lifecycle entrypoints for training orchestration."""

    async def start_session(
        self,
        db: AsyncSession,
        telegram_user_id: int,
        level: str,
        theme: str | None,
        *,
        total_questions: int,
        force_new: bool,
    ):
        return await self._start_topic_session(
            db,
            telegram_user_id,
            level=level,
            theme=theme,
            total_questions=total_questions,
            force_new=force_new,
            flow=self.SESSION_FLOW_REGULAR,
        )

    async def start_recommended_session(
        self,
        db: AsyncSession,
        telegram_user_id: int,
        level: str,
        theme: str | None,
        *,
        total_questions: int,
        force_new: bool,
    ):
        return await self._start_topic_session(
            db,
            telegram_user_id,
            level=level,
            theme=theme,
            total_questions=total_questions,
            force_new=force_new,
            flow=self.SESSION_FLOW_RECOMMENDED,
        )

    async def _start_topic_session(
        self,
        db: AsyncSession,
        telegram_user_id: int,
        *,
        level: str,
        theme: str | None,
        total_questions: int,
        force_new: bool,
        flow: str,
    ):
        user = await self.get_user(db, telegram_user_id)
        if self._entitlement_service is not None:
            await self._entitlement_service.ensure_daily_question_available(
                db,
                telegram_user_id,
                level=level,
                theme=theme,
            )
        await self._user_repo.set_training_preferences(db, telegram_user_id, level=level, theme=theme)
        await db.flush()
        await self._replace_active_session_if_needed(db, user.id, force_new=force_new)

        session = await self._session_repo.create(
            db,
            user_id=user.id,
            level=level,
            theme=theme,
            total_questions=max(1, total_questions),
            source=self.QUIZ_SOURCE,
            source_metadata=self._default_source_metadata(flow, telegram_user_id),
            api_metadata={"started_at": datetime.now(UTC).isoformat()},
        )
        await db.flush()
        await self._record_training_started(db, user_id=user.id, session=session, flow=flow)
        return session

    async def start_review_session(
        self,
        db: AsyncSession,
        telegram_user_id: int,
        *,
        force_new: bool,
        total_questions: int,
    ):
        if self._mistakes_service is None:
            raise NoReviewItemsError("Review service is not configured")

        user = await self.get_user(db, telegram_user_id)
        if self._entitlement_service is not None:
            await self._entitlement_service.ensure_entitlement(
                db,
                telegram_user_id,
                feature=FEATURE_MISTAKE_REPEAT,
            )
            await self._entitlement_service.ensure_daily_question_available(
                db,
                telegram_user_id,
            )
        await db.flush()
        review_items = await self._mistakes_service.get_review_items(db, telegram_user_id)
        if not review_items:
            raise NoReviewItemsError("No active mistakes to review")

        existing = await self._replace_review_session_if_needed(db, user.id, force_new=force_new)
        if existing is not None:
            return existing

        first_item = review_items[0]
        total = self._session_question_limit(total_questions, review_items)
        session = await self._session_repo.create(
            db,
            user_id=user.id,
            level=first_item.level,
            theme=first_item.theme,
            total_questions=total,
            source=self.QUIZ_SOURCE,
            source_metadata=self._default_source_metadata(self.SESSION_FLOW_REVIEW, telegram_user_id),
            api_metadata={"review_count": len(review_items)},
        )
        await db.flush()
        await self._record_training_started(
            db,
            user_id=user.id,
            session=session,
            flow=self.SESSION_FLOW_REVIEW,
            extra_metadata={"active_mistake_count": len(review_items)},
        )
        await self._record_analytics(
            db,
            event_name="mistakes_repeated",
            user_id=user.id,
            session_id=session.id,
            event_metadata={
                "active_mistake_count": len(review_items),
                "session_type": self.SESSION_FLOW_REVIEW,
            },
        )
        return session

    async def _replace_active_session_if_needed(self, db: AsyncSession, user_id: int, *, force_new: bool) -> None:
        existing = await self._session_repo.get_active_for_user(db, user_id)
        if existing is None:
            return
        if not force_new:
            raise ActiveSessionConflictError("Active training session exists")
        await self._session_repo.mark_cancelled(db, existing)

    async def _replace_review_session_if_needed(self, db: AsyncSession, user_id: int, *, force_new: bool):
        existing = await self._session_repo.get_active_for_user(db, user_id)
        if existing is None:
            return None
        if self._is_review_session(existing) and not force_new:
            return existing
        if not self._is_review_session(existing) and not force_new:
            raise ActiveSessionConflictError("Active training session exists")
        await self._session_repo.mark_cancelled(db, existing)
        return None

    async def _record_training_started(
        self,
        db: AsyncSession,
        *,
        user_id: int,
        session,
        flow: str,
        extra_metadata: dict[str, Any] | None = None,
    ) -> None:
        event_metadata = {
            "session_type": flow,
            "level": session.level,
            "theme": session.theme,
            "planned_question_count": session.total_questions,
        }
        if extra_metadata:
            event_metadata.update(extra_metadata)
        await self._record_analytics(
            db,
            event_name="training_started",
            user_id=user_id,
            session_id=session.id,
            event_metadata=event_metadata,
        )

    async def resume_or_start_review_session(
        self,
        db: AsyncSession,
        telegram_user_id: int,
        *,
        force_new: bool,
        total_questions: int,
    ) -> tuple[Any, QuizQuestionPayload]:
        session = await self.start_review_session(
            db,
            telegram_user_id,
            force_new=force_new,
            total_questions=total_questions,
        )
        question = await self.get_or_create_current_question(db, telegram_user_id, force_refresh=True)
        return session, question

    async def get_active_session(self, db: AsyncSession, telegram_user_id: int):
        user = await self._user_repo.get_by_telegram_id(db, telegram_user_id)
        if not user:
            return None
        return await self._session_repo.get_active_for_user(db, user.id)

    async def cancel_active_session(self, db: AsyncSession, telegram_user_id: int) -> bool:
        user = await self._user_repo.get_by_telegram_id(db, telegram_user_id)
        if not user:
            return False

        session = await self._session_repo.get_active_for_user(db, user.id)
        if not session:
            return False

        await self._session_repo.mark_cancelled(db, session)
        await self._session_repo.clear_pending_question(db, session)
        await self._record_analytics(
            db,
            event_name="training_abandoned",
            user_id=user.id,
            session_id=session.id,
            event_metadata={
                "session_type": self._session_flow(session),
                "level": session.level,
                "theme": session.theme,
                "answered_count": getattr(session, "answered_count", 0),
            },
        )
        await db.flush()
        return True

    async def resume_or_start_session(
        self,
        db: AsyncSession,
        telegram_user_id: int,
        level: str,
        theme: str,
        *,
        force_new: bool,
        total_questions: int,
    ) -> tuple[Any, QuizQuestionPayload]:
        session = await self.start_session(
            db,
            telegram_user_id,
            level=level,
            theme=theme,
            total_questions=total_questions,
            force_new=force_new,
        )
        question = await self.get_or_create_current_question(db, telegram_user_id, force_refresh=True)
        return session, question

    async def resume_or_start_recommended_session(
        self,
        db: AsyncSession,
        telegram_user_id: int,
        level: str,
        theme: str | None,
        *,
        force_new: bool,
        total_questions: int,
    ) -> tuple[Any, QuizQuestionPayload]:
        session = await self.start_recommended_session(
            db,
            telegram_user_id,
            level=level,
            theme=theme,
            total_questions=total_questions,
            force_new=force_new,
        )
        question = await self.get_or_create_current_question(db, telegram_user_id, force_refresh=True)
        return session, question
