from __future__ import annotations

from typing import Iterable

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import UserAnswer


class AnswerRepository:
    """Answer persistence helpers for training sessions."""

    async def create(
        self,
        db: AsyncSession,
        *,
        session_id: int,
        user_id: int,
        external_quiz_id: str,
        selected_answer: str,
        correct_answer: str,
        is_correct: bool,
        training_session_item_id: int | None = None,
        question_reference_id: int | None = None,
        quiz_source: str | None = None,
        external_ref: str | None = None,
        level: str | None = None,
        theme: str | None = None,
        theme_key: str | None = None,
        session_type: str = "regular",
        metadata_snapshot: dict[str, object] | None = None,
        telegram_update_id: int | None = None,
    ) -> UserAnswer:
        answer = UserAnswer(
            session_id=session_id,
            user_id=user_id,
            external_quiz_id=external_quiz_id,
            item_id=external_quiz_id,
            training_session_item_id=training_session_item_id,
            question_reference_id=question_reference_id,
            level=level,
            theme=theme,
            theme_key=theme_key,
            selected_answer=selected_answer,
            correct_answer=correct_answer,
            is_correct=is_correct,
            session_type=session_type,
            metadata_snapshot=metadata_snapshot,
            telegram_update_id=telegram_update_id,
            quiz_source=quiz_source,
            external_ref=external_ref,
        )
        db.add(answer)
        return answer

    async def get_by_session_and_question(
        self,
        db: AsyncSession,
        *,
        session_id: int,
        user_id: int,
        external_quiz_id: str,
    ) -> UserAnswer | None:
        query = select(UserAnswer).where(
            and_(
                UserAnswer.session_id == session_id,
                UserAnswer.user_id == user_id,
                UserAnswer.external_quiz_id == external_quiz_id,
            ),
        )
        return await db.scalar(query)

    async def get_by_telegram_update_id(
        self,
        db: AsyncSession,
        telegram_update_id: int,
    ) -> UserAnswer | None:
        query = select(UserAnswer).where(UserAnswer.telegram_update_id == telegram_update_id)
        return await db.scalar(query)

    async def count_by_session(self, db: AsyncSession, session_id: int) -> int:
        query = select(func.count()).select_from(UserAnswer).where(UserAnswer.session_id == session_id)
        return int((await db.scalar(query)) or 0)

    async def list_question_ids_by_session(self, db: AsyncSession, session_id: int) -> list[str]:
        query = (
            select(UserAnswer.external_quiz_id)
            .where(UserAnswer.session_id == session_id)
            .order_by(UserAnswer.id.asc())
        )
        result = await db.execute(query)
        return [str(item) for item, in result.all()]
