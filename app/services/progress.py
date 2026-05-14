from __future__ import annotations

from app.repositories.progress import ProgressRepository
from app.repositories.users import UserRepository


class ProgressService:
    """Runtime business logic for progress aggregation."""

    def __init__(
        self,
        *,
        user_repo: UserRepository | None = None,
        progress_repo: ProgressRepository | None = None,
    ) -> None:
        self._user_repo = user_repo or UserRepository()
        self._progress_repo = progress_repo or ProgressRepository()

    async def record_answer_result(
        self,
        db,
        telegram_user_id: int,
        *,
        level: str,
        theme: str | None,
        is_correct: bool,
        is_duplicate: bool,
    ):
        user = await self._user_repo.create_if_missing(db, telegram_user_id)
        progress = await self._progress_repo.get_or_create(
            db,
            user_id=user.id,
            level=level,
            theme=theme,
        )

        if is_duplicate:
            return progress

        await self._progress_repo.update_totals(
            db,
            progress,
            answered_delta=1,
            correct_delta=1 if is_correct else 0,
        )
        await self._progress_repo.update_streak_if_supported(progress, is_correct=is_correct)
        return progress

    async def get_user_summary(self, db, telegram_user_id: int) -> list:
        user = await self._user_repo.get_by_telegram_id(db, telegram_user_id)
        if user is None:
            return []
        return await self._progress_repo.get_user_summary(db, user_id=user.id)

    async def get_level_theme_summary(
        self,
        db,
        telegram_user_id: int,
        *,
        level: str | None = None,
        theme: str | None = None,
    ) -> list:
        user = await self._user_repo.get_by_telegram_id(db, telegram_user_id)
        if user is None:
            return []
        return await self._progress_repo.get_level_theme_summary(
            db,
            user_id=user.id,
            level=level,
            theme=theme,
        )

