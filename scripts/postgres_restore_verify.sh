#!/usr/bin/env bash

set -euo pipefail

if [[ "${1:-}" == "--help" ]]; then
  cat <<'USAGE'
Usage: BACKUP_FILE=/secure/path.dump RESTORE_DATABASE_URL=... \
  RESTORE_CONFIRM_NON_PRODUCTION=I_UNDERSTAND_THIS_IS_NOT_PRODUCTION \
  bash scripts/postgres_restore_verify.sh

Restores a backup into a disposable non-production database and verifies core
schema, payment idempotency constraints, and learning-data integrity checks.
The script refuses APP_ENV=production and never prints database URLs.
USAGE
  exit 0
fi

log() {
  printf '[postgres_restore_verify] %s\n' "$1"
}

fail() {
  printf '[postgres_restore_verify] %s\n' "$1" >&2
  exit 1
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || fail "missing command: $1"
}

require_command pg_restore
require_command psql
require_command sha256sum

if [[ "${APP_ENV:-}" == "production" ]]; then
  fail "restore verification must not run with APP_ENV=production"
fi
if [[ "${RESTORE_CONFIRM_NON_PRODUCTION:-}" != "I_UNDERSTAND_THIS_IS_NOT_PRODUCTION" ]]; then
  fail "RESTORE_CONFIRM_NON_PRODUCTION confirmation is required"
fi
if [[ -z "${BACKUP_FILE:-}" ]]; then
  fail "BACKUP_FILE is required"
fi
if [[ -z "${RESTORE_DATABASE_URL:-}" ]]; then
  fail "RESTORE_DATABASE_URL is required"
fi
if [[ ! -f "$BACKUP_FILE" ]]; then
  fail "BACKUP_FILE does not exist"
fi
if [[ -n "${DATABASE_URL:-}" && "$RESTORE_DATABASE_URL" == "$DATABASE_URL" ]]; then
  fail "RESTORE_DATABASE_URL must not equal DATABASE_URL"
fi

work_file="$(mktemp "${TMPDIR:-/tmp}/deutsch-trainer-restore.XXXXXX")"
sql_file="$(mktemp "${TMPDIR:-/tmp}/deutsch-trainer-restore-sql.XXXXXX")"

cleanup() {
  rm -f "$work_file" "$sql_file"
}
trap cleanup EXIT

rm -f "$work_file"
case "$BACKUP_FILE" in
  *.age)
    require_command age
    age --decrypt --output "$work_file" "$BACKUP_FILE"
    ;;
  *.gpg)
    require_command gpg
    gpg --batch --yes --decrypt --output "$work_file" "$BACKUP_FILE"
    ;;
  *)
    cp "$BACKUP_FILE" "$work_file"
    ;;
esac

if [[ -f "$BACKUP_FILE.sha256" ]]; then
  log "verifying backup checksum"
  sha256sum --check "$BACKUP_FILE.sha256" >/dev/null
fi

restore_args=(--dbname="$RESTORE_DATABASE_URL" --single-transaction --exit-on-error)
if [[ "${RESTORE_REPLACE_TARGET:-false}" == "true" ]]; then
  restore_args+=(--clean --if-exists)
fi

log "restoring into verification database"
pg_restore "${restore_args[@]}" "$work_file"

cat > "$sql_file" <<'SQL'
DO $$
DECLARE
    missing_count integer;
    duplicate_count integer;
    invalid_count integer;
BEGIN
    SELECT count(*) INTO missing_count
    FROM (
        VALUES
            ('users'),
            ('quiz_sessions'),
            ('question_references'),
            ('training_session_items'),
            ('user_answers'),
            ('progress'),
            ('progress_history'),
            ('mistakes'),
            ('mistake_history'),
            ('daily_limits'),
            ('subscriptions'),
            ('payments'),
            ('analytics_events'),
            ('api_error_logs')
    ) AS expected(table_name)
    WHERE to_regclass('public.' || expected.table_name) IS NULL;
    IF missing_count > 0 THEN
        RAISE EXCEPTION 'required restored tables are missing';
    END IF;

    SELECT count(*) INTO missing_count
    FROM (
        VALUES
            ('uq_payments_idempotency_key'),
            ('uq_payments_provider_payment_charge_id'),
            ('uq_progress_user_level_theme'),
            ('uq_user_answers_telegram_update_id')
    ) AS expected(constraint_name)
    WHERE NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = expected.constraint_name
    );
    IF missing_count > 0 THEN
        RAISE EXCEPTION 'required idempotency constraints are missing';
    END IF;

    SELECT count(*) INTO duplicate_count
    FROM (
        SELECT provider_payment_charge_id
        FROM payments
        WHERE provider_payment_charge_id IS NOT NULL
        GROUP BY provider_payment_charge_id
        HAVING count(*) > 1
    ) AS duplicates;
    IF duplicate_count > 0 THEN
        RAISE EXCEPTION 'duplicate provider payment charge ids found';
    END IF;

    SELECT count(*) INTO duplicate_count
    FROM (
        SELECT payment_id
        FROM subscriptions
        WHERE payment_id IS NOT NULL
        GROUP BY payment_id
        HAVING count(*) > 1
    ) AS duplicates;
    IF duplicate_count > 0 THEN
        RAISE EXCEPTION 'duplicate subscription credits found for one payment';
    END IF;

    SELECT count(*) INTO duplicate_count
    FROM (
        SELECT user_id, external_quiz_id
        FROM mistakes
        WHERE resolved_at IS NULL
        GROUP BY user_id, external_quiz_id
        HAVING count(*) > 1
    ) AS duplicates;
    IF duplicate_count > 0 THEN
        RAISE EXCEPTION 'duplicate active mistakes found';
    END IF;

    SELECT count(*) INTO invalid_count
    FROM progress
    WHERE total_correct > total_answered
       OR total_correct + wrong_count > total_answered
       OR total_answered < 0
       OR total_correct < 0
       OR wrong_count < 0;
    IF invalid_count > 0 THEN
        RAISE EXCEPTION 'invalid progress counters found';
    END IF;
END $$;
SQL

log "verifying restored schema and integrity checks"
psql --set ON_ERROR_STOP=1 --quiet "$RESTORE_DATABASE_URL" --file "$sql_file" >/dev/null

log "restore verification finished"
