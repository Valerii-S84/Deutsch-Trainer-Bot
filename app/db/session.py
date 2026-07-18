from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from time import perf_counter

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.ext.asyncio.session import AsyncSession

from app.config import Settings, get_settings
from app.db.base import Base

def create_engine(
    settings: Settings,
    *,
    pool_size: int | None = None,
    max_overflow: int | None = None,
    pool_timeout: float | None = None,
) -> AsyncEngine:
    """Create the async DB engine with runtime pool settings."""

    engine_kwargs = {
        "echo": False,
        "future": True,
    }
    if not settings.database_url.startswith("sqlite"):
        engine_kwargs.update(
            pool_size=pool_size if pool_size is not None else settings.db_pool_size,
            max_overflow=max_overflow if max_overflow is not None else settings.db_max_overflow,
            pool_timeout=pool_timeout if pool_timeout is not None else settings.db_pool_timeout,
            pool_recycle=settings.db_pool_recycle,
            pool_pre_ping=settings.db_pool_pre_ping,
        )
    return create_async_engine(settings.database_url, **engine_kwargs)


_settings = get_settings()
_engine = create_engine(_settings)
_worker_engine = create_engine(
    _settings,
    pool_size=_settings.worker_db_pool_size,
    max_overflow=_settings.worker_db_max_overflow,
    pool_timeout=_settings.worker_db_pool_timeout,
)

AsyncSessionLocal = async_sessionmaker(_engine, expire_on_commit=False, class_=AsyncSession)
WorkerSessionLocal = async_sessionmaker(_worker_engine, expire_on_commit=False, class_=AsyncSession)


@asynccontextmanager
async def get_session() -> AsyncIterator[AsyncSession]:
    """Yield a DB session."""
    async with AsyncSessionLocal() as session:
        yield session


async def measure_pool_wait_ms() -> float:
    """Measure one DB checkout plus ping, used by readiness and load evidence."""

    started = perf_counter()
    async with _engine.connect() as connection:
        await connection.execute(text("SELECT 1"))
    return (perf_counter() - started) * 1000


async def dispose_engine() -> None:
    """Close pooled database connections during runtime shutdown."""

    await _engine.dispose()
    if _worker_engine is not _engine:
        await _worker_engine.dispose()


__all__ = [
    "Base",
    "AsyncSessionLocal",
    "WorkerSessionLocal",
    "create_engine",
    "dispose_engine",
    "get_session",
    "measure_pool_wait_ms",
]
