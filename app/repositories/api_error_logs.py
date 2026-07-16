from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ApiErrorLog
from app.repositories.sqlite_compat import next_sqlite_id_if_needed


class ApiErrorLogRepository:
    """Append-only Quiz Bank API error diagnostics."""

    async def record(
        self,
        db: AsyncSession,
        *,
        endpoint: str,
        error_category: str,
        user_id: int | None = None,
        session_id: int | None = None,
        request_id: str | None = None,
        status_code: int | None = None,
        level: str | None = None,
        theme: str | None = None,
        error_metadata: dict[str, Any] | None = None,
    ) -> ApiErrorLog:
        error_log = ApiErrorLog(
            id=await next_sqlite_id_if_needed(db, ApiErrorLog),
            user_id=user_id,
            session_id=session_id,
            request_id=request_id,
            endpoint=endpoint,
            status_code=status_code,
            error_category=error_category,
            level=level,
            theme=theme,
            error_metadata=error_metadata,
            occurred_at=datetime.now(UTC),
        )
        db.add(error_log)
        return error_log
