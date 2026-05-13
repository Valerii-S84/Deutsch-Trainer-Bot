from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.ext.asyncio.session import AsyncSession

from app.config import get_settings
from app.db.base import Base

_settings = get_settings()
_engine = create_async_engine(
    _settings.database_url,
    echo=False,
    future=True,
    pool_pre_ping=True,
)

AsyncSessionLocal = async_sessionmaker(_engine, expire_on_commit=False, class_=AsyncSession)


async def get_session() -> AsyncIterator[AsyncSession]:
    """Yield a DB session."""
    async with AsyncSessionLocal() as session:
        yield session


__all__ = ["Base", "AsyncSessionLocal", "get_session"]

