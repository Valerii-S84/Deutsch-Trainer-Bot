#!/usr/bin/env bash

set -euo pipefail

if [[ -z "${VIRTUAL_ENV:-}" && -z "${CONDA_PREFIX:-}" ]]; then
  echo "Active virtual environment is required for runtime checks." >&2
  echo "Run: python3 -m venv .venv && . .venv/bin/activate" >&2
  exit 1
fi

if [[ -z "${DATABASE_URL:-${TEST_DATABASE_URL:-}}" ]]; then
  echo "DATABASE_URL or TEST_DATABASE_URL is required for runtime verification." >&2
  echo "Set one of them before running this script." >&2
  exit 1
fi

export DATABASE_URL="${DATABASE_URL:-${TEST_DATABASE_URL}}"

echo "[db_runtime_check] using DATABASE_URL=${DATABASE_URL}"

echo "[db_runtime_check] alembic upgrade head"
alembic upgrade head

echo "[db_runtime_check] alembic current"
alembic current

if command -v alembic >/dev/null; then
  echo "[db_runtime_check] alembic check"
  alembic check
fi

python3 - <<'PY'
from __future__ import annotations

import asyncio
import os

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine


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

REQUIRED_INDEXES = {
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

REQUIRED_UNIQUE_CONSTRAINTS = {
    "users": {"uq_users_telegram_user_id"},
    "user_answers": {"uq_user_answers_user_session_external_quiz"},
    "progress": {"uq_progress_user_level_theme"},
    "payments": {
        "uq_payments_idempotency_key",
        "uq_payments_provider_payment_charge_id",
    },
}

REQUIRED_JSONB = {
    "quiz_sessions": {"source_metadata", "api_metadata"},
    "mistakes": {"source_snapshot"},
    "payments": {"audit_metadata"},
    "analytics_events": {"event_metadata"},
}


async def assert_runtime_schema(database_url: str) -> None:
    engine = create_async_engine(database_url)

    try:
        async with engine.connect() as connection:
            for table in EXPECTED_TABLES:
                exists = await connection.scalar(
                    text("SELECT to_regclass(:table) IS NOT NULL"),
                    {"table": f"public.{table}"},
                )
                assert exists, f"Table missing: {table}"

            for table, indexes in REQUIRED_INDEXES.items():
                for idx in indexes:
                    present = await connection.scalar(
                        text(
                            """
                            SELECT 1
                            FROM pg_indexes
                            WHERE schemaname='public' AND tablename=:table AND indexname=:idx
                            """,
                        ),
                        {"table": table, "idx": idx},
                    )
                    assert present is not None, f"Index missing: {table}.{idx}"

            for table, constraints in REQUIRED_UNIQUE_CONSTRAINTS.items():
                for constraint in constraints:
                    present = await connection.scalar(
                        text(
                            """
                            SELECT 1
                            FROM pg_constraint c
                            JOIN pg_class t ON t.oid = c.conrelid
                            WHERE t.relname = :table
                              AND c.conname = :constraint
                              AND c.contype = 'u'
                            """,
                        ),
                        {"table": table, "constraint": constraint},
                    )
                    assert present is not None, f"Unique constraint missing: {table}.{constraint}"

            partial = await connection.scalar(
                text(
                    """
                    SELECT indexdef
                    FROM pg_indexes
                    WHERE schemaname='public' AND tablename='mistakes' AND indexname='ix_mistakes_active_user_external'
                    """,
                ),
            )
            assert partial is not None, "Partial unique index for unresolved mistakes missing"
            partial_lower = " ".join(partial.lower().split())
            assert "create unique index" in partial_lower, "Partial index must be unique"
            assert "resolved_at is null" in partial_lower, "Partial index must filter resolved_at IS NULL"

            for table, columns in REQUIRED_JSONB.items():
                for column in columns:
                    udt = await connection.scalar(
                        text(
                            """
                            SELECT udt_name
                            FROM information_schema.columns
                            WHERE table_schema='public' AND table_name=:table AND column_name=:column
                            """,
                        ),
                        {"table": table, "column": column},
                    )
                    assert udt == "jsonb", f"Expected jsonb for {table}.{column}, got {udt}"
    finally:
        await engine.dispose()


asyncio.run(assert_runtime_schema(os.environ["DATABASE_URL"]))
PY

echo "[db_runtime_check] runtime schema verification finished"

