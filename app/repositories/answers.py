from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Iterable

from sqlalchemy import and_, func, select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import UserAnswer


@dataclass(frozen=True)
class AnswerWriteResult:
    id: int
    session_id: int
    user_id: int
    external_quiz_id: str
    selected_answer: str
    correct_answer: str
    is_correct: bool
    answered_at: datetime | None
    created: bool


@dataclass(frozen=True)
class AnswerContentFields:
    catalog_id: str | None = None
    item_id: str | None = None
    item_version: str | None = None
    quiz_source: str | None = None
    external_ref: str | None = None
    level: str | None = None
    theme: str | None = None
    theme_key: str | None = None


@dataclass(frozen=True)
class AnswerCreateData:
    session_id: int
    user_id: int
    external_quiz_id: str
    selected_answer: str
    correct_answer: str
    is_correct: bool
    training_session_item_id: int | None = None
    question_reference_id: int | None = None
    content_fields: AnswerContentFields = field(default_factory=AnswerContentFields)
    session_type: str = "regular"
    metadata_snapshot: dict[str, object] | None = None
    telegram_update_id: int | None = None


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
        content_fields: AnswerContentFields | None = None,
        session_type: str = "regular",
        metadata_snapshot: dict[str, object] | None = None,
        telegram_update_id: int | None = None,
    ) -> UserAnswer:
        data = AnswerCreateData(
            session_id=session_id,
            user_id=user_id,
            external_quiz_id=external_quiz_id,
            selected_answer=selected_answer,
            correct_answer=correct_answer,
            is_correct=is_correct,
            training_session_item_id=training_session_item_id,
            question_reference_id=question_reference_id,
            content_fields=content_fields or AnswerContentFields(),
            session_type=session_type,
            metadata_snapshot=metadata_snapshot,
            telegram_update_id=telegram_update_id,
        )
        answer = UserAnswer(**_answer_values(data))
        db.add(answer)
        return answer

    async def create_idempotent(
        self,
        db: AsyncSession,
        data: AnswerCreateData,
    ) -> AnswerWriteResult:
        """Insert an answer once without raising on duplicate PostgreSQL conflicts."""

        if _dialect_name(db) == "postgresql":
            return await self._create_idempotent_postgresql(db, data)

        answer = await self.create(db, **_create_kwargs(data))
        await db.flush()
        return _result_from_model(answer, created=True)

    async def _create_idempotent_postgresql(
        self,
        db: AsyncSession,
        data: AnswerCreateData,
    ) -> AnswerWriteResult:
        statement = (
            postgresql_insert(UserAnswer)
            .values(**_answer_values(data))
            .on_conflict_do_nothing()
            .returning(*_returning_columns())
        )
        row = (await db.execute(statement)).mappings().first()
        if row is not None:
            return _result_from_mapping(row, created=True)

        existing = await self._existing_after_conflict(db, data)
        if existing is None:
            raise RuntimeError("Answer insert conflicted but existing answer was not found")
        return _result_from_model(existing, created=False)

    async def _existing_after_conflict(
        self,
        db: AsyncSession,
        data: AnswerCreateData,
    ) -> UserAnswer | None:
        if data.telegram_update_id is not None:
            existing = await self.get_by_telegram_update_id(db, data.telegram_update_id)
            if existing is not None:
                return existing
        return await self.get_by_session_and_question(
            db,
            session_id=data.session_id,
            user_id=data.user_id,
            external_quiz_id=data.external_quiz_id,
        )

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


def _dialect_name(db: AsyncSession) -> str:
    return db.get_bind().dialect.name


def _answer_values(data: AnswerCreateData) -> dict[str, object]:
    content = data.content_fields
    return {
        "session_id": data.session_id,
        "user_id": data.user_id,
        "external_quiz_id": data.external_quiz_id,
        "training_session_item_id": data.training_session_item_id,
        "question_reference_id": data.question_reference_id,
        "catalog_id": content.catalog_id,
        "item_id": content.item_id or data.external_quiz_id,
        "item_version": content.item_version,
        "level": content.level,
        "theme": content.theme,
        "theme_key": content.theme_key,
        "selected_answer": data.selected_answer,
        "correct_answer": data.correct_answer,
        "is_correct": data.is_correct,
        "session_type": data.session_type,
        "metadata_snapshot": data.metadata_snapshot,
        "telegram_update_id": data.telegram_update_id,
        "quiz_source": content.quiz_source,
        "external_ref": content.external_ref,
    }


def _create_kwargs(data: AnswerCreateData) -> dict[str, object]:
    values = _answer_values(data)
    values["content_fields"] = data.content_fields
    values.pop("catalog_id")
    values.pop("item_id")
    values.pop("item_version")
    values.pop("level")
    values.pop("theme")
    values.pop("theme_key")
    values.pop("quiz_source")
    values.pop("external_ref")
    return values


def _returning_columns() -> tuple:
    return (
        UserAnswer.id,
        UserAnswer.session_id,
        UserAnswer.user_id,
        UserAnswer.external_quiz_id,
        UserAnswer.selected_answer,
        UserAnswer.correct_answer,
        UserAnswer.is_correct,
        UserAnswer.answered_at,
    )


def _result_from_mapping(row, *, created: bool) -> AnswerWriteResult:
    return AnswerWriteResult(
        id=int(row["id"]),
        session_id=int(row["session_id"]),
        user_id=int(row["user_id"]),
        external_quiz_id=str(row["external_quiz_id"]),
        selected_answer=str(row["selected_answer"]),
        correct_answer=str(row["correct_answer"]),
        is_correct=bool(row["is_correct"]),
        answered_at=row["answered_at"],
        created=created,
    )


def _result_from_model(answer: UserAnswer, *, created: bool) -> AnswerWriteResult:
    return AnswerWriteResult(
        id=int(answer.id),
        session_id=int(answer.session_id),
        user_id=int(answer.user_id),
        external_quiz_id=str(answer.external_quiz_id),
        selected_answer=str(answer.selected_answer),
        correct_answer=str(answer.correct_answer),
        is_correct=bool(answer.is_correct),
        answered_at=answer.answered_at,
        created=created,
    )
