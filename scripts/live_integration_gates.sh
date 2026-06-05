#!/usr/bin/env bash

set -euo pipefail

if [[ "${1:-}" == "--help" ]]; then
  cat <<'USAGE'
Usage: bash scripts/live_integration_gates.sh

Runs staging/live integration gates for protected environments.
Required env:
  DATABASE_URL or TEST_DATABASE_URL
  REDIS_URL
  SMOKE_BASE_URL
  BOT_TOKEN with RUN_TELEGRAM_SMOKE=1
  Quiz Bank protected env with RUN_QUIZ_BANK_SMOKE=1
  TELEGRAM_STARS_EVIDENCE_FILE

The script does not deploy, register webhooks, send Telegram messages, or create
payments. Telegram Stars is verified from a non-secret sandbox evidence JSON.
USAGE
  exit 0
fi

fail() {
  printf '[live_integration_gates] %s\n' "$1" >&2
  exit 1
}

enabled() {
  case "${!1:-}" in
    1|true|TRUE|yes|YES) return 0 ;;
    *) return 1 ;;
  esac
}

export PYTHON_BIN="${PYTHON_BIN:-python3}"
export ALLOW_SYSTEM_PYTHON="${ALLOW_SYSTEM_PYTHON:-1}"

[[ -n "${DATABASE_URL:-${TEST_DATABASE_URL:-}}" ]] || fail "DATABASE_URL or TEST_DATABASE_URL is required"
[[ -n "${REDIS_URL:-}" ]] || fail "REDIS_URL is required"
[[ -n "${SMOKE_BASE_URL:-}" ]] || fail "SMOKE_BASE_URL is required"
enabled RUN_TELEGRAM_SMOKE || fail "RUN_TELEGRAM_SMOKE=1 is required"
enabled RUN_QUIZ_BANK_SMOKE || fail "RUN_QUIZ_BANK_SMOKE=1 is required"
[[ -n "${TELEGRAM_STARS_EVIDENCE_FILE:-}" ]] || fail "TELEGRAM_STARS_EVIDENCE_FILE is required"

echo "[live_integration_gates] running PostgreSQL migration/runtime gate"
bash scripts/db_runtime_check.sh

echo "[live_integration_gates] running Redis runtime gate"
"$PYTHON_BIN" scripts/redis_runtime_check.py

echo "[live_integration_gates] running app, Telegram and Quiz Bank smoke gates"
bash scripts/ops_smoke.sh

echo "[live_integration_gates] validating Telegram Stars sandbox evidence"
"$PYTHON_BIN" scripts/payment_sandbox_evidence_check.py "$TELEGRAM_STARS_EVIDENCE_FILE"

echo "[live_integration_gates] live integration gates passed"
