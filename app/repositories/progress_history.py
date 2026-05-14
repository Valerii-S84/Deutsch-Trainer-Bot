from __future__ import annotations

from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Progress, ProgressHistory


class ProgressHistoryRepository:
    """Append-only history writes for progress changes."""

    async def record_answer_change(
        self,
        db: AsyncSession,
        *,
        progress: Progress,
        previous_status: str | None,
        previous_scores: dict[str, Any] | None,
        session_id: int | None,
        user_answer_id: int | None,
        reason_code: str,
    ) -> ProgressHistory:
        history = ProgressHistory(
            id=await self._next_id_if_needed(db),
            progress_id=progress.id,
            user_id=progress.user_id,
            session_id=session_id,
            user_answer_id=user_answer_id,
            level=progress.level,
            theme=progress.theme,
            event_type="answer_recorded",
            previous_status=previous_status,
            new_status=progress.topic_status,
            previous_scores=previous_scores,
            new_scores=self.snapshot_scores(progress),
            delta=self._delta(previous_scores, self.snapshot_scores(progress)),
            reason_code=reason_code,
        )
        db.add(history)
        return history

    @staticmethod
    def snapshot_scores(progress: Progress) -> dict[str, Any]:
        return {
            "total_answered": int(progress.total_answered or 0),
            "total_correct": int(progress.total_correct or 0),
            "wrong_count": int(getattr(progress, "wrong_count", 0) or 0),
            "accuracy": _to_json_number(progress.accuracy),
            "coverage_score": _to_json_number(getattr(progress, "coverage_score", None)),
            "stability_score": _to_json_number(getattr(progress, "stability_score", None)),
            "weakness_score": _to_json_number(getattr(progress, "weakness_score", None)),
            "recency_score": _to_json_number(getattr(progress, "recency_score", None)),
            "topic_status": progress.topic_status,
        }

    @staticmethod
    def _delta(
        previous_scores: dict[str, Any] | None,
        new_scores: dict[str, Any],
    ) -> dict[str, Any] | None:
        if previous_scores is None:
            return None
        return {
            "answered_delta": int(new_scores["total_answered"]) - int(previous_scores["total_answered"]),
            "correct_delta": int(new_scores["total_correct"]) - int(previous_scores["total_correct"]),
            "wrong_delta": int(new_scores["wrong_count"]) - int(previous_scores["wrong_count"]),
        }

    async def _next_id_if_needed(self, db: AsyncSession) -> int | None:
        if db.get_bind().dialect.name != "sqlite":
            return None
        max_id = await db.scalar(select(func.max(ProgressHistory.id)))
        return (max_id or 0) + 1


def _to_json_number(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
