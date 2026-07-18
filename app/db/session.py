from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from time import perf_counter
from uuid import uuid4

from sqlalchemy.engine import make_url
from sqlalchemy.pool import NullPool
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.ext.asyncio.session import AsyncSession

from app.config import DbConnectionBackend, Settings, get_settings
from app.db.base import Base


def create_engine(
    settings: Settings,
    *,
    pool_size: int | None = None,
    max_overflow: int | None = None,
    pool_timeout: float | None = None,
    use_queue_pool_for_pgbouncer: bool = False,
) -> AsyncEngine:
    """Create the async DB engine with runtime pool settings."""

    database_url = _database_url(settings)
    engine_kwargs = {
        "echo": False,
        "future": True,
    }
    if not database_url.startswith("sqlite"):
        if settings.db_connection_backend == DbConnectionBackend.pgbouncer_transaction:
            engine_kwargs.update(connect_args=_pgbouncer_connect_args())
            if settings.db_pgbouncer_uses_null_pool and not use_queue_pool_for_pgbouncer:
                engine_kwargs.update(poolclass=NullPool)
            else:
                engine_kwargs.update(
                    pool_size=pool_size if pool_size is not None else settings.db_pool_size,
                    max_overflow=max_overflow if max_overflow is not None else settings.db_max_overflow,
                    pool_timeout=pool_timeout if pool_timeout is not None else settings.db_pool_timeout,
                    pool_recycle=settings.db_pool_recycle,
                    pool_pre_ping=settings.db_pool_pre_ping,
                )
        else:
            engine_kwargs.update(
                pool_size=pool_size if pool_size is not None else settings.db_pool_size,
                max_overflow=max_overflow if max_overflow is not None else settings.db_max_overflow,
                pool_timeout=pool_timeout if pool_timeout is not None else settings.db_pool_timeout,
                pool_recycle=settings.db_pool_recycle,
                pool_pre_ping=settings.db_pool_pre_ping,
            )
    return create_async_engine(database_url, **engine_kwargs)


def _database_url(settings: Settings) -> str:
    if settings.db_connection_backend != DbConnectionBackend.pgbouncer_transaction:
        return settings.database_url
    if settings.database_url.startswith("sqlite"):
        return settings.database_url
    url = make_url(settings.database_url).update_query_dict(
        {"prepared_statement_cache_size": "0"},
        append=False,
    )
    return url.render_as_string(hide_password=False)


def _pgbouncer_connect_args() -> dict[str, object]:
    return {
        "statement_cache_size": 0,
        "prepared_statement_name_func": _prepared_statement_name,
    }


def _prepared_statement_name() -> str:
    return f"__asyncpg_{uuid4().hex}__"


_settings = get_settings()
_engine = create_engine(_settings)
_worker_engine = create_engine(
    _settings,
    pool_size=_settings.worker_db_pool_size,
    max_overflow=_settings.worker_db_max_overflow,
    pool_timeout=_settings.worker_db_pool_timeout,
    use_queue_pool_for_pgbouncer=True,
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
