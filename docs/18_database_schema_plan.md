# Deutsch Trainer Bot — Database Schema Plan (Milestone 2)

## 1) Scope for Milestone 2

For this milestone we implement only production data persistence and migration
infrastructure:

- users
- quiz sessions
- question references
- training session items
- user answers
- progress
- progress history
- mistakes
- mistake history
- recommendations
- daily limits
- subscriptions
- payments
- analytics events
- API error logs

No quiz flow, Telegram handlers, Quiz Bank API calls, or payment webhook
processing are implemented here.

## 2) Ownership and Data Boundaries

Canonical quiz content remains in Quiz Bank API.

Persistent records in this bot database store only runtime identifiers and minimal
snapshots required for:

- user state and access
- session and answer history
- progress aggregates
- payment/audit trail
- analytics

`external_quiz_id` is stored for audit and idempotency, not full Quiz Bank payloads.

## 3) Planned Tables

- `users`
  - Telegram identity fields: `telegram_user_id`, `username`, `first_name`
  - language/interface fields: `language_code`, `selected_level`, `selected_theme`
  - safety/access fields: `is_blocked`, `status`
  - timestamps: `created_at`, `updated_at`, `last_active_at`
- `quiz_sessions`
  - runtime session state: `user_id`, `level`, `theme`, `status`, `started_at`,
    `finished_at`, `total_questions`, `correct_answers`
  - source metadata fields: `source`, `source_metadata`, `api_request_id`, `api_metadata`
- `question_references`
  - minimal Quiz Bank item reference: `item_id`, `level`, `theme`, `theme_key`,
    `source`, `metadata_snapshot`, `content_version`, snapshots, `fetched_at`
- `training_session_items`
  - shown-item lifecycle: `session_id`, `user_id`, `question_reference_id`,
    `item_id`, `position`, `status`, `shown_at`, `answered_at`,
    `daily_limit_id`, `daily_limit_charged_at`
- `user_answers`
  - answer facts: `session_id`, `user_id`, `external_quiz_id`,
    `selected_answer`, `correct_answer`, `is_correct`, `answered_at`,
    `response_time_ms`
- `progress`
  - aggregate state: `user_id`, `level`, `theme`,
    `total_answered`, `total_correct`, `accuracy`, `streak`, `updated_at`
- `progress_history`
  - append-only progress events with score snapshots and reason codes
- `mistakes`
  - mistake state: `user_id`, `external_quiz_id`, `level`, `theme`,
    `wrong_answer`, `correct_answer`, `mistake_count`, `last_seen_at`,
    `resolved_at`, `status`
- `mistake_history`
  - append-only mistake lifecycle events with status and answer snapshots
- `recommendations`
  - generated next action with German copy and source snapshot
- `daily_limits`
  - Europe/Berlin usage counters by `user_id`, `limit_date`, and `plan`
- `subscriptions`
  - access state: `user_id`, `plan`, `status`, `started_at`, `expires_at`,
    `source`, `provider_reference`, `payment_id`, timestamps
- `payments`
  - crediting state: `user_id`, `telegram_payment_charge_id`,
    `provider_payment_charge_id`, `plan`, `amount_stars`, `config_reference`,
    `status`, `idempotency_key`, `paid_at`, `failed_at`, `source`, `audit_metadata`
- `analytics_events`
  - append-only events: `user_id`, `event_name`, `event_time`,
    `event_metadata`, `session_id`, `source`
- `api_error_logs`
  - Quiz Bank API failure diagnostics without secrets or raw sensitive payloads

## 4) Indexes and Constraints

- Users
  - unique constraint/index on `telegram_user_id`
- User answers
  - unique constraint on (`user_id`, `session_id`, `external_quiz_id`)
  - unique nullable idempotency constraint on `telegram_update_id`
  - index on `user_id`, `session_id`, `external_quiz_id`
- Question references
  - unique constraint on `item_id`
- Training session items
  - unique constraint on (`session_id`, `position`)
  - unique constraint on (`session_id`, `item_id`)
- Daily limits
  - unique constraint on (`user_id`, `limit_date`, `plan`)
- Mistakes
  - index on `user_id`
  - index on `external_quiz_id`
  - partial unique index on unresolved (`user_id`, `external_quiz_id`)
- Subscriptions
  - composite index on (`status`, `expires_at`)
- Payments
  - unique constraints on `idempotency_key` and `provider_payment_charge_id`
  - index on `user_id`
- Analytics
  - composite index on (`event_name`, `event_time`)
  - index on `session_id`, `user_id`
- API error logs
  - indexes on `occurred_at`, `error_category`, `user_id`, `session_id`
- Progress and other operational queries
  - index on `user_id`

## 4.1) Migration rollback and forward-fix policy

- Every schema change is represented by an Alembic revision in
  `alembic/versions/`.
- `downgrade()` must reverse the DDL for local/staging rollback validation.
- Production data corrections use forward-fix migrations rather than rewriting
  already applied migration files.
- Runtime validation must run `alembic upgrade head`, `alembic current`,
  `alembic check`, and PostgreSQL schema tests before marking DB work verified.

## 5) Security and Secret Handling

- No secret fields are persisted in any schema table.
- Analytics and payment metadata use JSONB only for non-sensitive context.
- No API keys and no Telegram tokens are written to database records.
