from __future__ import annotations

from typing import Any

from app.db.models import Mistake
from app.repositories.mistakes import MistakeRepository
from app.repositories.users import UserRepository


class MistakeService:
    """Runtime service for user mistake tracking and review lifecycle."""

    def __init__(
        self,
        *,
        user_repo: UserRepository | None = None,
        mistake_repo: MistakeRepository | None = None,
    ) -> None:
        self._user_repo = user_repo or UserRepository()
        self._mistake_repo = mistake_repo or MistakeRepository()

    async def _get_user(self, db, telegram_user_id: int):
        return await self._user_repo.create_if_missing(db, telegram_user_id)

    async def record_wrong_answer(
        self,
        db,
        telegram_user_id: int,
        *,
        external_quiz_id: str,
        level: str,
        theme: str | None,
        wrong_answer: str,
        correct_answer: str,
        is_duplicate: bool = False,
        source_snapshot: dict[str, Any] | None = None,
    ) -> Mistake | None:
        if is_duplicate:
            user = await self._user_repo.get_by_telegram_id(db, telegram_user_id)
            if user is None:
                return None
            return await self._mistake_repo.get_active_by_user_and_external_quiz_id(
                db,
                user_id=user.id,
                external_quiz_id=external_quiz_id,
            )

        user = await self._get_user(db, telegram_user_id)
        existing = await self._mistake_repo.find_active_by_user_and_external_quiz_id(
            db,
            user_id=user.id,
            external_quiz_id=external_quiz_id,
        )
        if existing is not None:
            return await self._mistake_repo.increment_wrong(
                db,
                existing,
                wrong_answer=wrong_answer,
                correct_answer=correct_answer,
                source_snapshot=source_snapshot,
            )

        resolved = await self._mistake_repo.get_by_user_and_external_quiz_id(
            db,
            user_id=user.id,
            external_quiz_id=external_quiz_id,
            active_only=False,
        )
        if resolved is not None and resolved.resolved_at is not None:
            return await self._mistake_repo.reopen_as_active(
                db,
                resolved,
                wrong_answer=wrong_answer,
                correct_answer=correct_answer,
                source_snapshot=source_snapshot,
            )

        return await self._mistake_repo.create(
            db,
            user_id=user.id,
            external_quiz_id=external_quiz_id,
            level=level,
            theme=theme or "",
            wrong_answer=wrong_answer,
            correct_answer=correct_answer,
            source_snapshot=source_snapshot,
        )

    async def record_review_success(
        self,
        db,
        telegram_user_id: int,
        *,
        external_quiz_id: str,
        question_level: str | None,
        question_theme: str | None,
        correct_answer: str,
    ) -> Mistake | None:
        user = await self._user_repo.get_by_telegram_id(db, telegram_user_id)
        if user is None:
            return None

        mistake = await self._mistake_repo.find_active_by_user_and_external_quiz_id(
            db,
            user_id=user.id,
            external_quiz_id=external_quiz_id,
        )
        if mistake is None:
            return None

        return await self._mistake_repo.resolve(db, mistake)

    async def get_review_items(self, db, telegram_user_id: int) -> list[Mistake]:
        user = await self._user_repo.get_by_telegram_id(db, telegram_user_id)
        if user is None:
            return []
        return await self._mistake_repo.list_active_for_user(db, user_id=user.id)

    async def get_weak_areas(self, db, telegram_user_id: int) -> list[dict[str, object]]:
        user = await self._user_repo.get_by_telegram_id(db, telegram_user_id)
        if user is None:
            return []
        return await self._mistake_repo.get_weak_area_summary(db, user_id=user.id)
