from __future__ import annotations

from datetime import UTC, datetime
import re
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AnalyticsEvent

_EVENT_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{1,127}$")
_SOURCE_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_UNSAFE_METADATA_KEY_PARTS = (
    "api_key",
    "authorization",
    "credential",
    "debug_payload",
    "password",
    "provider_payload",
    "raw_payload",
    "secret",
    "token",
)


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
        reason_code = _rejection_reason(event_name=event_name, source=source, event_metadata=event_metadata)
        if reason_code is not None:
            event_metadata = {
                "rejected_event_name": _safe_text(event_name, max_length=128),
                "reason_code": reason_code,
            }
            event_name = "analytics_event_rejected"
            source = "analytics"
            session_id = None

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


async def has_user_event_since(
    db: AsyncSession,
    *,
    user_id: int,
    event_name: str,
    since: datetime,
) -> bool:
    existing = await db.scalar(
        select(AnalyticsEvent.id)
        .where(
            AnalyticsEvent.user_id == user_id,
            AnalyticsEvent.event_name == event_name,
            AnalyticsEvent.event_time >= since,
        )
        .limit(1),
    )
    return existing is not None


def _rejection_reason(
    *,
    event_name: str,
    source: str,
    event_metadata: dict[str, Any] | None,
) -> str | None:
    if not _EVENT_NAME_RE.match(event_name):
        return "invalid_event_name"
    if not _SOURCE_RE.match(source):
        return "invalid_source"
    if _metadata_has_unsafe_key(event_metadata):
        return "unsafe_metadata"
    return None


def _metadata_has_unsafe_key(value: object) -> bool:
    if isinstance(value, dict):
        for key, child in value.items():
            key_text = str(key).lower()
            if any(part in key_text for part in _UNSAFE_METADATA_KEY_PARTS):
                return True
            if _metadata_has_unsafe_key(child):
                return True
    if isinstance(value, list):
        return any(_metadata_has_unsafe_key(item) for item in value)
    return False


def _safe_text(value: object, *, max_length: int) -> str:
    return str(value).replace("\n", " ")[:max_length]
