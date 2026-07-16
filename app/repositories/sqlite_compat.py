from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession


async def next_sqlite_id_if_needed(db: AsyncSession, model: type[Any]) -> int | None:
    if db.get_bind().dialect.name != "sqlite":
        return None
    max_id = await db.scalar(select(func.max(model.id)))
    return (max_id or 0) + 1
