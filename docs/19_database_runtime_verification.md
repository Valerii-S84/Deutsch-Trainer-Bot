# Milestone 2 — PostgreSQL Runtime Verification

## Status

- Runtime verification on PostgreSQL is **completed**.

## Runtime evidence

- `docker` check:
  - `docker version` → Client 28.4.0, Server 28.4.0 (Docker Desktop 4.46.0)
  - `docker compose version` → 2.39.4-desktop.1
  - `docker ps` shows existing containers and `deutschtrainerbot-db-1` once started.
- PostgreSQL availability:
  - `docker compose -f docker-compose.yml -f /tmp/compose-db-runtime.yml up -d db`
  - `docker compose -f docker-compose.yml -f /tmp/compose-db-runtime.yml ps` → `deutschtrainerbot-db-1` `Up` with `0.0.0.0:5433->5432/tcp`
  - `docker compose -f docker-compose.yml -f /tmp/compose-db-runtime.yml logs db --tail=100` shows PostgreSQL 16.12 init and ready state.
- Alembic/runtime proof (with
  `DATABASE_URL='postgresql+asyncpg://postgres:postgres@localhost:5433/deutsch_trainer'`
  and `TEST_DATABASE_URL` same):
  - `alembic upgrade head` → applied without error (`202605140001 (head)`)
  - `alembic current` → `202605140001 (head)`
  - `alembic check` → `No new upgrade operations detected.`
  - `bash scripts/db_runtime_check.sh` → `runtime schema verification finished`
  - `python -m pytest -q tests/test_db_runtime_schema.py --capture=no` → passed.

## Verified schema objects

- Tables: `users`, `quiz_sessions`, `user_answers`, `progress`, `mistakes`, `subscriptions`, `payments`, `analytics_events`
- Indexes:
  - `ix_users_telegram_user_id`
  - `ix_users_language_code`
  - `ix_user_answers_user_id`
  - `ix_user_answers_session_id`
  - `ix_user_answers_external_quiz_id`
  - `ix_mistakes_user_id`
  - `ix_mistakes_external_quiz_id`
  - `ix_mistakes_active_user_external` (partial unique with `WHERE resolved_at IS NULL`)
  - `ix_progress_user_id`
  - `ix_progress_level_theme`
  - `ix_payments_user_id`
  - `ix_subscriptions_user_id`
  - `ix_subscriptions_status_expires_at`
  - `ix_analytics_events_user_id`
  - `ix_analytics_events_session_id`
  - `ix_analytics_events_event_name_time`
  - `ix_quiz_sessions_user_id`
- Constraints:
  - `uq_users_telegram_user_id`
  - `uq_user_answers_user_session_external_quiz`
  - `uq_progress_user_level_theme`
  - `uq_payments_idempotency_key`
  - `uq_payments_provider_payment_charge_id`
  - `ix_mistakes_active_user_external` (partial unique index)
- JSONB columns verified on PostgreSQL:
  - `quiz_sessions.source_metadata`
  - `quiz_sessions.api_metadata`
  - `mistakes.source_snapshot`
  - `payments.audit_metadata`
  - `analytics_events.event_metadata`
