from __future__ import annotations

from datetime import UTC, datetime
import re
from typing import Any

from sqlalchemy import insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AnalyticsEvent
from app.repositories.sqlite_compat import next_sqlite_id_if_needed

_EVENT_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{1,127}$")
_SOURCE_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_UNSAFE_METADATA_KEY_PARTS = (
    "api_key",
    "authorization",
    "credential",
    "debug_payload",
    "dsn",
    "password",
    "provider_payload",
    "raw_payload",
    "secret",
    "token",
)
_UNSAFE_METADATA_VALUE_RE = re.compile(
    r"(?i)(\bbearer\s+[A-Za-z0-9._~+/=-]+"
    r"|\b(?:authorization|token|secret|api[_-]?key|password|credential|database_url|dsn)\b\s*[:=]"
    r"|\b\d{8,12}:[A-Za-z0-9_-]{35,}"
    r"|-----BEGIN (?:RSA |EC |OPENSSH |)PRIVATE KEY-----)",
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
            id=await next_sqlite_id_if_needed(db, AnalyticsEvent),
            user_id=user_id,
            event_name=event_name,
            event_time=datetime.now(UTC),
            event_metadata=event_metadata,
            session_id=session_id,
            source=source,
        )
        db.add(event)
        return event

    async def record_many(
        self,
        db: AsyncSession,
        events: list[dict[str, Any]],
    ) -> list[AnalyticsEvent]:
        if not events:
            return []

        sanitized_events = [self._sanitized_event(values) for values in events]
        if db.get_bind().dialect.name == "postgresql":
            rows = await db.execute(insert(AnalyticsEvent).returning(*AnalyticsEvent.__table__.c), sanitized_events)
            return [AnalyticsEvent(**dict(row)) for row in rows.mappings().all()]

        models = []
        for values in sanitized_events:
            models.append(
                AnalyticsEvent(
                    id=await next_sqlite_id_if_needed(db, AnalyticsEvent),
                    **values,
                ),
            )
        db.add_all(models)
        return models

    def _sanitized_event(self, values: dict[str, Any]) -> dict[str, Any]:
        event_name = str(values["event_name"])
        source = str(values.get("source", "bot"))
        event_metadata = values.get("event_metadata")
        session_id = values.get("session_id")
        reason_code = _rejection_reason(event_name=event_name, source=source, event_metadata=event_metadata)
        if reason_code is not None:
            event_metadata = {
                "rejected_event_name": _safe_text(event_name, max_length=128),
                "reason_code": reason_code,
            }
            event_name = "analytics_event_rejected"
            source = "analytics"
            session_id = None

        return {
            "user_id": values.get("user_id"),
            "event_name": event_name,
            "event_time": datetime.now(UTC),
            "event_metadata": event_metadata,
            "session_id": session_id,
            "source": source,
        }


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
    if _metadata_has_unsafe_content(event_metadata):
        return "unsafe_metadata"
    return None


def _metadata_has_unsafe_content(value: object) -> bool:
    if isinstance(value, dict):
        for key, child in value.items():
            key_text = str(key).lower()
            if any(part in key_text for part in _UNSAFE_METADATA_KEY_PARTS):
                return True
            if _metadata_has_unsafe_content(child):
                return True
    if isinstance(value, list):
        return any(_metadata_has_unsafe_content(item) for item in value)
    if isinstance(value, str):
        return bool(_UNSAFE_METADATA_VALUE_RE.search(value))
    return False


def _safe_text(value: object, *, max_length: int) -> str:
    return str(value).replace("\n", " ")[:max_length]
