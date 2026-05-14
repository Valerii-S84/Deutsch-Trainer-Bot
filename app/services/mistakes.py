from __future__ import annotations

from typing import Any

from app.db.models import Mistake
from app.repositories.mistake_history import MistakeHistoryRepository
from app.repositories.mistakes import MistakeRepository
from app.repositories.users import UserRepository


class MistakeService:
    """Runtime service for user mistake tracking and review lifecycle."""

    def __init__(
        self,
        *,
        user_repo: UserRepository | None = None,
        mistake_repo: MistakeRepository | None = None,
        mistake_history_repo: MistakeHistoryRepository | None = None,
    ) -> None:
        self._user_repo = user_repo or UserRepository()
        self._mistake_repo = mistake_repo or MistakeRepository()
        self._mistake_history_repo = mistake_history_repo or MistakeHistoryRepository()

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
        session_id: int | None = None,
        user_answer_id: int | None = None,
        metadata_snapshot: dict[str, Any] | None = None,
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
            previous_status = _status_value(existing.status)
            mistake = await self._mistake_repo.increment_wrong(
                db,
                existing,
                wrong_answer=wrong_answer,
                correct_answer=correct_answer,
                source_snapshot=source_snapshot,
            )
            await self._record_history(
                db,
                mistake,
                event_type="wrong_repeated",
                previous_status=previous_status,
                user_answer_id=user_answer_id,
                session_id=session_id,
                wrong_answer=wrong_answer,
                correct_answer=correct_answer,
                metadata_snapshot=metadata_snapshot,
            )
            return mistake

        resolved = await self._mistake_repo.get_by_user_and_external_quiz_id(
            db,
            user_id=user.id,
            external_quiz_id=external_quiz_id,
            active_only=False,
        )
        if resolved is not None and resolved.resolved_at is not None:
            previous_status = _status_value(resolved.status)
            mistake = await self._mistake_repo.reopen_as_active(
                db,
                resolved,
                wrong_answer=wrong_answer,
                correct_answer=correct_answer,
                source_snapshot=source_snapshot,
            )
            await self._record_history(
                db,
                mistake,
                event_type="wrong_reopened",
                previous_status=previous_status,
                user_answer_id=user_answer_id,
                session_id=session_id,
                wrong_answer=wrong_answer,
                correct_answer=correct_answer,
                metadata_snapshot=metadata_snapshot,
            )
            return mistake

        mistake = await self._mistake_repo.create(
            db,
            user_id=user.id,
            external_quiz_id=external_quiz_id,
            level=level,
            theme=theme or "",
            wrong_answer=wrong_answer,
            correct_answer=correct_answer,
            source_snapshot=source_snapshot,
        )
        if hasattr(db, "flush"):
            await db.flush()
        await self._record_history(
            db,
            mistake,
            event_type="wrong_created",
            previous_status=None,
            user_answer_id=user_answer_id,
            session_id=session_id,
            wrong_answer=wrong_answer,
            correct_answer=correct_answer,
            metadata_snapshot=metadata_snapshot,
        )
        return mistake

    async def record_review_success(
        self,
        db,
        telegram_user_id: int,
        *,
        external_quiz_id: str,
        question_level: str | None,
        question_theme: str | None,
        correct_answer: str,
        session_id: int | None = None,
        user_answer_id: int | None = None,
        metadata_snapshot: dict[str, Any] | None = None,
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

        previous_status = _status_value(mistake.status)
        resolved = await self._mistake_repo.resolve(db, mistake)
        await self._record_history(
            db,
            resolved,
            event_type="review_success",
            previous_status=previous_status,
            user_answer_id=user_answer_id,
            session_id=session_id,
            correct_answer=correct_answer,
            metadata_snapshot=metadata_snapshot,
        )
        return resolved

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

    async def _record_history(
        self,
        db,
        mistake: Mistake,
        *,
        event_type: str,
        previous_status: str | None,
        user_answer_id: int | None,
        session_id: int | None,
        wrong_answer: str | None = None,
        correct_answer: str | None = None,
        metadata_snapshot: dict[str, Any] | None = None,
    ) -> None:
        await self._mistake_history_repo.record(
            db,
            mistake=mistake,
            event_type=event_type,
            previous_status=previous_status,
            user_answer_id=user_answer_id,
            session_id=session_id,
            wrong_answer=wrong_answer,
            correct_answer=correct_answer,
            metadata_snapshot=metadata_snapshot,
        )


def _status_value(status: object) -> str:
    return str(status.value if hasattr(status, "value") else status)
