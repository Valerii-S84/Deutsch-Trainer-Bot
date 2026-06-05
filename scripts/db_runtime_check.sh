#!/usr/bin/env bash

set -euo pipefail

PYTHON_BIN="${PYTHON_BIN:-python3}"

if [[ -z "${VIRTUAL_ENV:-}" && -z "${CONDA_PREFIX:-}" && "${CI:-}" != "true" && "${ALLOW_SYSTEM_PYTHON:-0}" != "1" ]]; then
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

echo "[db_runtime_check] DATABASE_URL is set"

echo "[db_runtime_check] alembic upgrade head"
"$PYTHON_BIN" -m alembic upgrade head

echo "[db_runtime_check] alembic current"
"$PYTHON_BIN" -m alembic current

echo "[db_runtime_check] alembic check"
"$PYTHON_BIN" -m alembic check

"$PYTHON_BIN" - <<'PY'
from __future__ import annotations

import asyncio
import os

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine


EXPECTED_TABLES = {
    "users",
    "quiz_sessions",
    "question_references",
    "training_session_items",
    "user_answers",
    "progress",
    "progress_history",
    "mistakes",
    "mistake_history",
    "recommendations",
    "daily_limits",
    "subscriptions",
    "payments",
    "analytics_events",
    "api_error_logs",
}

REQUIRED_INDEXES = {
    "users": {"ix_users_telegram_user_id", "ix_users_language_code"},
    "quiz_sessions": {"ix_quiz_sessions_user_id", "ix_quiz_sessions_user_status"},
    "question_references": {
        "ix_question_references_level_theme",
        "ix_question_references_theme_key",
    },
    "training_session_items": {
        "ix_training_session_items_user_id",
        "ix_training_session_items_session_status",
        "ix_training_session_items_question_reference_id",
        "ix_training_session_items_daily_limit_id",
    },
    "user_answers": {
        "ix_user_answers_user_id",
        "ix_user_answers_session_id",
        "ix_user_answers_external_quiz_id",
        "ix_user_answers_training_session_item_id",
        "ix_user_answers_question_reference_id",
    },
    "progress": {"ix_progress_user_id", "ix_progress_level_theme"},
    "progress_history": {
        "ix_progress_history_user_created",
        "ix_progress_history_progress_id",
        "ix_progress_history_session_id",
    },
    "mistakes": {
        "ix_mistakes_user_id",
        "ix_mistakes_external_quiz_id",
        "ix_mistakes_question_reference_id",
        "ix_mistakes_item_id",
    },
    "mistake_history": {
        "ix_mistake_history_user_created",
        "ix_mistake_history_mistake_id",
        "ix_mistake_history_item_id",
    },
    "recommendations": {"ix_recommendations_user_priority", "ix_recommendations_user_created"},
    "daily_limits": {"ix_daily_limits_user_date"},
    "subscriptions": {"ix_subscriptions_user_id", "ix_subscriptions_status_expires_at"},
    "payments": {"ix_payments_user_id"},
    "analytics_events": {
        "ix_analytics_events_user_id",
        "ix_analytics_events_session_id",
        "ix_analytics_events_event_name_time",
    },
    "api_error_logs": {
        "ix_api_error_logs_occurred_at",
        "ix_api_error_logs_error_category",
        "ix_api_error_logs_user_id",
        "ix_api_error_logs_session_id",
    },
}

REQUIRED_UNIQUE_CONSTRAINTS = {
    "users": {"uq_users_telegram_user_id"},
    "question_references": {"uq_question_references_item_id"},
    "training_session_items": {
        "uq_training_session_items_session_position",
        "uq_training_session_items_session_item",
    },
    "user_answers": {"uq_user_answers_user_session_external_quiz", "uq_user_answers_telegram_update_id"},
    "progress": {"uq_progress_user_level_theme"},
    "daily_limits": {"uq_daily_limits_user_date_plan"},
    "payments": {
        "uq_payments_idempotency_key",
        "uq_payments_telegram_payment_charge_id",
        "uq_payments_provider_payment_charge_id",
    },
}

REQUIRED_JSONB = {
    "quiz_sessions": {"source_metadata", "api_metadata"},
    "question_references": {"metadata_snapshot"},
    "user_answers": {"metadata_snapshot"},
    "progress_history": {"previous_scores", "new_scores", "delta"},
    "mistakes": {"source_snapshot"},
    "mistake_history": {"metadata_snapshot"},
    "recommendations": {"source_snapshot"},
    "payments": {"audit_metadata"},
    "analytics_events": {"event_metadata"},
    "api_error_logs": {"metadata"},
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
