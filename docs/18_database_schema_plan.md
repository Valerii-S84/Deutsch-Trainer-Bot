# Deutsch Trainer Bot — Database Schema Plan (Milestone 2)

## 1) Scope for Milestone 2

For this milestone we implement only production data persistence and migration
infrastructure:

- users
- quiz sessions
- user answers
- progress
- mistakes
- subscriptions
- payments
- analytics events

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
- `user_answers`
  - answer facts: `session_id`, `user_id`, `external_quiz_id`,
    `selected_answer`, `correct_answer`, `is_correct`, `answered_at`,
    `response_time_ms`
- `progress`
  - aggregate state: `user_id`, `level`, `theme`,
    `total_answered`, `total_correct`, `accuracy`, `streak`, `updated_at`
- `mistakes`
  - mistake state: `user_id`, `external_quiz_id`, `level`, `theme`,
    `wrong_answer`, `correct_answer`, `mistake_count`, `last_seen_at`,
    `resolved_at`, `status`
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

## 4) Indexes and Constraints

- Users
  - unique constraint/index on `telegram_user_id`
- User answers
  - unique constraint on (`user_id`, `session_id`, `external_quiz_id`)
  - index on `user_id`, `session_id`, `external_quiz_id`
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
- Progress and other operational queries
  - index on `user_id`

## 5) Security and Secret Handling

- No secret fields are persisted in any schema table.
- Analytics and payment metadata use JSONB only for non-sensitive context.
- No API keys and no Telegram tokens are written to database records.
