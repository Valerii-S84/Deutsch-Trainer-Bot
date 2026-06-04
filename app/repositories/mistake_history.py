from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Mistake, MistakeHistory


class MistakeHistoryRepository:
    """Append-only history writes for mistake lifecycle changes."""

    async def record(
        self,
        db: AsyncSession,
        *,
        mistake: Mistake,
        event_type: str,
        previous_status: str | None,
        user_answer_id: int | None = None,
        session_id: int | None = None,
        wrong_answer: str | None = None,
        correct_answer: str | None = None,
        metadata_snapshot: dict[str, Any] | None = None,
    ) -> MistakeHistory:
        history = MistakeHistory(
            id=await self._next_id_if_needed(db),
            mistake_id=mistake.id,
            user_id=mistake.user_id,
            user_answer_id=user_answer_id,
            session_id=session_id,
            item_id=mistake.item_id or mistake.external_quiz_id,
            event_type=event_type,
            previous_status=previous_status,
            new_status=str(mistake.status.value if hasattr(mistake.status, "value") else mistake.status),
            wrong_answer=wrong_answer,
            correct_answer=correct_answer,
            metadata_snapshot=metadata_snapshot,
        )
        db.add(history)
        return history

    async def _next_id_if_needed(self, db: AsyncSession) -> int | None:
        if db.get_bind().dialect.name != "sqlite":
            return None
        max_id = await db.scalar(select(func.max(MistakeHistory.id)))
        return (max_id or 0) + 1
