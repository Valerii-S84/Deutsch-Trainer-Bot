# Milestone 2 — PostgreSQL Runtime Verification

## Status

- Runtime verification on PostgreSQL is **completed**.

## Runtime evidence

- Current extended schema verification:
  - temporary PostgreSQL 16 container started with
    `POSTGRES_DB=deutsch_trainer` and host port `55432`
  - `DATABASE_URL` / `TEST_DATABASE_URL` pointed to the temporary local
    PostgreSQL instance
  - `bash scripts/db_runtime_check.sh` → applied Alembic head
    `202605140002`, `alembic check` returned no new upgrade operations, and
    runtime schema verification finished
  - `python -m pytest -q tests/test_db_runtime_schema.py --capture=no` → passed

## Previous Base-Schema Evidence

- `docker` check:
  - `docker version` → Client 28.4.0, Server 28.4.0 (Docker Desktop 4.46.0)
  - `docker compose version` → 2.39.4-desktop.1
  - `docker ps` shows existing containers and `deutschtrainerbot-db-1` once started.
- PostgreSQL availability:
  - `docker compose -f docker-compose.yml -f /tmp/compose-db-runtime.yml up -d db`
  - `docker compose -f docker-compose.yml -f /tmp/compose-db-runtime.yml ps` → `deutschtrainerbot-db-1` `Up` with `0.0.0.0:5433->5432/tcp`
  - `docker compose -f docker-compose.yml -f /tmp/compose-db-runtime.yml logs db --tail=100` shows PostgreSQL 16.12 init and ready state.
- Alembic/runtime proof with local PostgreSQL test URLs set:
  - `alembic upgrade head` → applied without error (`202605140001 (head)`)
  - `alembic current` → `202605140001 (head)`
  - `alembic check` → `No new upgrade operations detected.`
  - `bash scripts/db_runtime_check.sh` → `runtime schema verification finished`
  - `python -m pytest -q tests/test_db_runtime_schema.py --capture=no` → passed.

## Verified schema objects

- Tables: `users`, `quiz_sessions`, `question_references`, `training_session_items`,
  `user_answers`, `progress`, `progress_history`, `mistakes`, `mistake_history`,
  `recommendations`, `daily_limits`, `subscriptions`, `payments`,
  `analytics_events`, `api_error_logs`
- Indexes:
  - `ix_users_telegram_user_id`
  - `ix_users_language_code`
  - `ix_quiz_sessions_user_id`
  - `ix_quiz_sessions_user_status`
  - `ix_question_references_level_theme`
  - `ix_question_references_theme_key`
  - `ix_training_session_items_user_id`
  - `ix_training_session_items_session_status`
  - `ix_training_session_items_question_reference_id`
  - `ix_training_session_items_daily_limit_id`
  - `ix_user_answers_user_id`
  - `ix_user_answers_session_id`
  - `ix_user_answers_external_quiz_id`
  - `ix_user_answers_training_session_item_id`
  - `ix_user_answers_question_reference_id`
  - `ix_progress_history_user_created`
  - `ix_progress_history_progress_id`
  - `ix_progress_history_session_id`
  - `ix_mistakes_user_id`
  - `ix_mistakes_external_quiz_id`
  - `ix_mistakes_question_reference_id`
  - `ix_mistakes_item_id`
  - `ix_mistakes_active_user_external` (partial unique with `WHERE resolved_at IS NULL`)
  - `ix_progress_user_id`
  - `ix_progress_level_theme`
  - `ix_mistake_history_user_created`
  - `ix_mistake_history_mistake_id`
  - `ix_mistake_history_item_id`
  - `ix_recommendations_user_priority`
  - `ix_recommendations_user_created`
  - `ix_daily_limits_user_date`
  - `ix_payments_user_id`
  - `ix_subscriptions_user_id`
  - `ix_subscriptions_status_expires_at`
  - `ix_analytics_events_user_id`
  - `ix_analytics_events_session_id`
  - `ix_analytics_events_event_name_time`
  - `ix_api_error_logs_occurred_at`
  - `ix_api_error_logs_error_category`
  - `ix_api_error_logs_user_id`
  - `ix_api_error_logs_session_id`
- Constraints:
  - `uq_users_telegram_user_id`
  - `uq_question_references_item_id`
  - `uq_training_session_items_session_position`
  - `uq_training_session_items_session_item`
  - `uq_user_answers_user_session_external_quiz`
  - `uq_user_answers_telegram_update_id`
  - `uq_progress_user_level_theme`
  - `uq_daily_limits_user_date_plan`
  - `uq_payments_idempotency_key`
  - `uq_payments_provider_payment_charge_id`
  - `ix_mistakes_active_user_external` (partial unique index)
- JSONB columns verified on PostgreSQL:
  - `quiz_sessions.source_metadata`
  - `quiz_sessions.api_metadata`
  - `question_references.metadata_snapshot`
  - `user_answers.metadata_snapshot`
  - `progress_history.previous_scores`
  - `progress_history.new_scores`
  - `progress_history.delta`
  - `mistakes.source_snapshot`
  - `mistake_history.metadata_snapshot`
  - `recommendations.source_snapshot`
  - `payments.audit_metadata`
  - `analytics_events.event_metadata`
  - `api_error_logs.metadata`
