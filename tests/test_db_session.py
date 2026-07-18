from __future__ import annotations

from sqlalchemy.pool import NullPool

from app.config import DbConnectionBackend, Settings
from app.db.session import _prepared_statement_name, create_engine


def test_create_engine_uses_queue_pool_in_direct_mode() -> None:
    settings = _settings(DbConnectionBackend.direct)

    engine = create_engine(settings)

    try:
        assert engine.sync_engine.url.query.get("prepared_statement_cache_size") is None
        assert not isinstance(engine.sync_engine.pool, NullPool)
    finally:
        engine.sync_engine.dispose()


def test_create_engine_uses_null_pool_for_pgbouncer_transaction_mode() -> None:
    settings = _settings(DbConnectionBackend.pgbouncer_transaction, reuse_app_connections=False)

    engine = create_engine(settings)

    try:
        assert engine.sync_engine.url.query["prepared_statement_cache_size"] == "0"
        assert isinstance(engine.sync_engine.pool, NullPool)
    finally:
        engine.sync_engine.dispose()


def test_create_engine_reuses_queue_pool_for_pgbouncer_transaction_when_enabled() -> None:
    settings = _settings(DbConnectionBackend.pgbouncer_transaction, reuse_app_connections=True)

    engine = create_engine(settings)

    try:
        assert engine.sync_engine.url.query["prepared_statement_cache_size"] == "0"
        assert not isinstance(engine.sync_engine.pool, NullPool)
    finally:
        engine.sync_engine.dispose()


def test_prepared_statement_name_is_unique() -> None:
    assert _prepared_statement_name() != _prepared_statement_name()


def _settings(backend: DbConnectionBackend, *, reuse_app_connections: bool = False) -> Settings:
    return Settings(
        DATABASE_URL="postgresql+asyncpg://postgres:postgres@localhost:5432/deutsch_trainer",
        DB_CONNECTION_BACKEND=backend.value,
        DB_PGBOUNCER_REUSE_APP_CONNECTIONS=reuse_app_connections,
        DB_APP_REPLICA_COUNT=1,
        DB_WORKER_REPLICA_COUNT=0,
        DB_WORKER_CLIENT_BUDGET_PER_REPLICA=5,
        DB_POOL_SIZE=20,
        DB_MAX_OVERFLOW=10,
        DB_POOL_TIMEOUT=5,
        DB_POOL_RECYCLE=1800,
        DB_POOL_PRE_PING=True,
        WORKER_DB_POOL_SIZE=10,
        WORKER_DB_MAX_OVERFLOW=5,
        WORKER_DB_POOL_TIMEOUT=5,
        FREE_DAILY_QUESTION_LIMIT=5,
        PLUS_DAILY_QUESTION_LIMIT=25,
        PRO_DAILY_QUESTION_LIMIT=100,
    )
