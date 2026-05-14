from __future__ import annotations

import os

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine


EXPECTED_TABLES = {
    "users",
    "quiz_sessions",
    "user_answers",
    "progress",
    "mistakes",
    "subscriptions",
    "payments",
    "analytics_events",
}

EXPECTED_INDEXES = {
    "users": {"ix_users_telegram_user_id", "ix_users_language_code"},
    "user_answers": {
        "ix_user_answers_user_id",
        "ix_user_answers_session_id",
        "ix_user_answers_external_quiz_id",
    },
    "mistakes": {
        "ix_mistakes_user_id",
        "ix_mistakes_external_quiz_id",
    },
    "subscriptions": {"ix_subscriptions_user_id", "ix_subscriptions_status_expires_at"},
    "payments": {"ix_payments_user_id"},
    "analytics_events": {
        "ix_analytics_events_user_id",
        "ix_analytics_events_session_id",
        "ix_analytics_events_event_name_time",
    },
    "quiz_sessions": {"ix_quiz_sessions_user_id"},
    "progress": {"ix_progress_user_id", "ix_progress_level_theme"},
}

EXPECTED_UNIQUE_CONSTRAINTS = {
    "users": {"uq_users_telegram_user_id"},
    "user_answers": {"uq_user_answers_user_session_external_quiz"},
    "progress": {"uq_progress_user_level_theme"},
    "payments": {
        "uq_payments_idempotency_key",
        "uq_payments_provider_payment_charge_id",
    },
}

EXPECTED_JSONB = {
    "quiz_sessions": {"source_metadata", "api_metadata"},
    "mistakes": {"source_snapshot"},
    "payments": {"audit_metadata"},
    "analytics_events": {"event_metadata"},
}


def _resolve_database_url() -> str:
    database_url = os.environ.get("DATABASE_URL") or os.environ.get("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("DATABASE_URL or TEST_DATABASE_URL is required for runtime schema test")
    return database_url


@pytest_asyncio.fixture
async def db_connection() -> AsyncConnection:
    database_url = _resolve_database_url()
    engine: AsyncEngine = create_async_engine(database_url)

    try:
        async with engine.connect() as connection:
            yield connection
    except Exception as exc:
        pytest.skip(f"PostgreSQL runtime verification skipped: cannot connect ({exc.__class__.__name__})")
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_postgres_tables_exist(db_connection: AsyncConnection) -> None:
    connection = db_connection
    for table in EXPECTED_TABLES:
        exists = await connection.scalar(
            text("SELECT to_regclass(:table) IS NOT NULL"),
            {"table": f"public.{table}"},
        )
        assert exists, f"Table missing: {table}"


@pytest.mark.asyncio
async def test_postgres_indexes_exist(db_connection: AsyncConnection) -> None:
    connection = db_connection
    for table, index_names in EXPECTED_INDEXES.items():
        for index_name in index_names:
            present = await connection.scalar(
                text(
                    """
                    SELECT 1
                    FROM pg_indexes
                    WHERE schemaname='public' AND tablename=:table AND indexname=:index_name
                    """,
                ),
                {"table": table, "index_name": index_name},
            )
            assert present is not None, f"Index missing: {table}.{index_name}"


@pytest.mark.asyncio
async def test_postgres_constraints_exist(db_connection: AsyncConnection) -> None:
    connection = db_connection
    for table, constraints in EXPECTED_UNIQUE_CONSTRAINTS.items():
        for constraint_name in constraints:
            present = await connection.scalar(
                text(
                    """
                    SELECT 1
                    FROM pg_constraint c
                    JOIN pg_class t ON t.oid = c.conrelid
                    WHERE t.relname = :table
                      AND c.conname = :constraint_name
                      AND c.contype = 'u'
                    """,
                ),
                {"table": table, "constraint_name": constraint_name},
            )
            assert present is not None, f"Constraint missing: {table}.{constraint_name}"


@pytest.mark.asyncio
async def test_postgres_partial_unique_index_for_active_mistakes(db_connection: AsyncConnection) -> None:
    index_def = await db_connection.scalar(
        text(
            """
            SELECT indexdef
            FROM pg_indexes
            WHERE schemaname='public' AND tablename='mistakes' AND indexname='ix_mistakes_active_user_external'
            """,
        ),
    )
    assert index_def is not None, "Partial unique index for unresolved mistakes is missing"
    normalized = " ".join(index_def.lower().split())
    assert "create unique index" in normalized, "Index ix_mistakes_active_user_external must be unique"
    assert "resolved_at is null" in normalized, "Index ix_mistakes_active_user_external must filter unresolved rows"


@pytest.mark.asyncio
async def test_postgres_jsonb_fields(db_connection: AsyncConnection) -> None:
    for table, columns in EXPECTED_JSONB.items():
        for column in columns:
            udt_name = await db_connection.scalar(
                text(
                    """
                    SELECT udt_name
                    FROM information_schema.columns
                    WHERE table_schema='public' AND table_name=:table AND column_name=:column
                    """,
                ),
                {"table": table, "column": column},
            )
            assert udt_name == "jsonb", f"Expected jsonb type for {table}.{column}, got {udt_name}"

