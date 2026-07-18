# Deutsch Trainer Bot — Database Schema Plan (Milestone 2)

## 1) Scope for Milestone 2

For this milestone we implement only production data persistence and migration
infrastructure:

- users
- local quiz catalogs
- local quiz catalog items
- local quiz catalog import runs
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

No quiz flow, Telegram handlers, remote API calls, or payment webhook processing
are implemented here.

## 2) Ownership and Data Boundaries

Deutsch Trainer Bot owns a read-only Local Quiz Catalog for runtime gameplay.
The catalog is imported from snapshot data sources such as `ProductionQuizBank/`
into PostgreSQL before runtime use.

Remote Quiz Bank API is out of scope for training gameplay. It must not be used
by `next question`, answer validation, progress, mistakes or daily gameplay
state.

Persistent records in this bot database store catalog content plus runtime
identifiers and minimal snapshots required for:

- user state and access
- local catalog versioning and rollback
- session and answer history
- progress aggregates
- payment/audit trail
- analytics

Snapshot CSV/JSON files are catalog data sources, not runtime storage. Gameplay
must read questions from PostgreSQL/Redis, never directly from snapshot files.

Historical user records must keep stable catalog references so changing
`ACTIVE_CATALOG_ID` or importing a new bank never breaks old answers.

## 3) Planned Tables

- `users`
  - Telegram identity fields: `telegram_user_id`, `username`, `first_name`
  - language/interface fields: `language_code`, `selected_level`, `selected_theme`
  - safety/access fields: `is_blocked`, `status`
  - timestamps: `created_at`, `updated_at`, `last_active_at`
- `quiz_catalogs`
  - version identity: `catalog_id`, `catalog_version`, `source`, `checksum`,
    `imported_at`, `is_active`
  - import metadata: source path, manifest checksum, item counts, failure counts,
    importer version, imported by environment
- `quiz_catalog_items`
  - stable item identity: `catalog_id`, `item_id`, `item_version`
  - content: `language`, `level`, `sublevel`, `theme_id`, `theme`, `subtheme_id`,
    `objective_id`, `pattern_id`, `difficulty_band`, `register`, `prompt`,
    `stem_text`, answer options, `answer_key`, explanation, tags
  - operational fields: `status`, `is_active`, `checksum`, `source`,
    `source_path`, `selection_key`, `imported_at`, `metadata`
- `quiz_catalog_import_runs`
  - import execution audit: `catalog_id`, `catalog_version`, `source_path`,
    `manifest_checksum`, `dry_run`, `started_at`, `finished_at`, `status`,
    `added_count`, `updated_count`, `skipped_count`, `failed_count`,
    `error_summary`
- `quiz_sessions`
  - runtime session state: `user_id`, `level`, `theme`, `status`, `started_at`,
    `finished_at`, `total_questions`, `correct_answers`
  - catalog fields: `catalog_id`, `catalog_version`
  - source metadata fields: `source`, `source_metadata`, `api_metadata`
- `question_references`
  - minimal local catalog item reference: `catalog_id`, `item_id`,
    `item_version`, `level`, `theme`, `theme_key`, `source`,
    `metadata_snapshot`, snapshots, `fetched_at`
- `training_session_items`
  - shown-item lifecycle: `session_id`, `user_id`, `question_reference_id`,
    `catalog_id`, `item_id`, `item_version`, `position`, `status`,
    `shown_at`, `answered_at`,
    `daily_limit_id`, `daily_limit_charged_at`
- `user_answers`
  - answer facts: `session_id`, `user_id`, `catalog_id`, `item_id`,
    `item_version`, `selected_answer`, `correct_answer`, `is_correct`,
    `answered_at`, `response_time_ms`
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
  - external API or operational failure diagnostics without secrets or raw
    sensitive payloads

## 4) Indexes and Constraints

- Users
  - unique constraint/index on `telegram_user_id`
- User answers
  - unique constraint on (`user_id`, `session_id`, `catalog_id`, `item_id`)
  - unique nullable idempotency constraint on `telegram_update_id`
  - index on `user_id`, `session_id`, `catalog_id`, `item_id`
- Local quiz catalogs
  - unique constraint on `catalog_id`
  - unique constraint on (`catalog_id`, `catalog_version`)
  - index on `is_active`
- Local quiz catalog items
  - unique constraint on (`catalog_id`, `item_id`, `item_version`)
  - index on (`catalog_id`, `language`, `level`, `theme_id`, `status`, `is_active`, `selection_key`)
  - index on (`catalog_id`, `language`, `sublevel`, `theme_id`, `status`, `is_active`, `selection_key`)
  - index on (`catalog_id`, `status`, `is_active`)
  - checksum is stored for idempotent repeated imports
  - `selection_key` stores a deterministic imported hash for indexed selection
    without `ORDER BY RANDOM()` on large catalogs
- Local quiz catalog import runs
  - index on (`catalog_id`, `started_at`)
  - index on `status`
- Question references
  - unique constraint on (`catalog_id`, `item_id`, `item_version`)
  - non-unique index on `item_id` for legacy lookups; `item_id` alone is not
    globally unique across catalogs
- Training session items
  - unique constraint on (`session_id`, `position`)
  - unique constraint on (`session_id`, `catalog_id`, `item_id`)
- Daily limits
  - unique constraint on (`user_id`, `limit_date`, `plan`)
- Mistakes
  - index on `user_id`
  - index on `external_quiz_id`
  - partial unique index on unresolved (`user_id`, `external_quiz_id`)
- Subscriptions
  - composite index on (`status`, `expires_at`)
- Payments
  - unique constraints on `idempotency_key`, `telegram_payment_charge_id` and `provider_payment_charge_id`
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
- Catalog rollback is performed by changing `ACTIVE_CATALOG_ID` to a previously
  imported catalog. Old catalog rows are not deleted automatically.
- Catalog import migrations must be non-destructive by default and must not
  delete historical items required by user answer history.

## 4.2) Catalog versioning and switching

Each imported bank is identified by `catalog_id` and `catalog_version`.

Each item is identified by:

- `catalog_id`
- `item_id`
- `item_version`

Required catalog fields:

- `catalog_id`
- `catalog_version`
- `item_id`
- `item_version`
- `source`
- `checksum`
- `imported_at`
- `is_active`

`ACTIVE_CATALOG_ID` selects the catalog used for new gameplay. New catalogs may
be imported next to old catalogs. Old catalogs remain available for rollback and
for historical answer interpretation. If an item disappears from a new catalog,
old `user_answers`, `training_session_items`, `question_references`, progress
history and mistake history must still resolve through their stored
`catalog_id`, `item_id` and `item_version`.

The catalog schema supports CEFR levels A1 through C2. Runtime enabled levels
are a separate configuration concern; unsupported UI/gameplay levels must not be
served accidentally just because catalog rows exist.

## 5) Security and Secret Handling

- No secret fields are persisted in any schema table.
- Analytics and payment metadata use JSONB only for non-sensitive context.
- No API keys and no Telegram tokens are written to database records.
- Catalog snapshot files and imported question text are product data, not
  secrets, but they are runtime-critical data and must be backed up and restored
  with the Bot DB.
