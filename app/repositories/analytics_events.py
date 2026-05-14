from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AnalyticsEvent


class AnalyticsEventRepository:
    """Append-only analytics event writes with privacy-safe metadata."""

    async def record(
        self,
        db: AsyncSession,
        *,
        event_name: str,
        user_id: int | None,
        session_id: int | None = None,
        event_metadata: dict[str, Any] | None = None,
        source: str = "bot",
    ) -> AnalyticsEvent:
        event = AnalyticsEvent(
            id=await self._next_id_if_needed(db),
            user_id=user_id,
            event_name=event_name,
            event_time=datetime.now(UTC),
            event_metadata=event_metadata,
            session_id=session_id,
            source=source,
        )
        db.add(event)
        return event

    async def _next_id_if_needed(self, db: AsyncSession) -> int | None:
        if db.get_bind().dialect.name != "sqlite":
            return None
        max_id = await db.scalar(select(func.max(AnalyticsEvent.id)))
        return (max_id or 0) + 1
