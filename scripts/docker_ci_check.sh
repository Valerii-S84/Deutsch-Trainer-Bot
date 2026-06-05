#!/usr/bin/env bash

set -euo pipefail

if [[ "${1:-}" == "--help" ]]; then
  cat <<'USAGE'
Usage: bash scripts/docker_ci_check.sh

Validates Docker Compose config files and builds the application image.
This script does not start services, deploy, or read secret files.
USAGE
  exit 0
fi

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    printf '[docker_ci_check] missing command: %s\n' "$1" >&2
    exit 1
  fi
}

require_command docker

export APP_NAME="${APP_NAME:-deutsch-trainer-bot-ci}"
export BOT_IMAGE="${BOT_IMAGE:-deutsch-trainer-bot:ci}"
export BOT_TOKEN="${BOT_TOKEN:-ci-bot-token-placeholder}"
export TELEGRAM_WEBHOOK_URL="${TELEGRAM_WEBHOOK_URL:-https://ci.example.invalid}"
export TELEGRAM_WEBHOOK_PATH="${TELEGRAM_WEBHOOK_PATH:-/telegram/webhook}"
export TELEGRAM_WEBHOOK_SECRET="${TELEGRAM_WEBHOOK_SECRET:-ci-webhook-secret}"
export DATABASE_URL="${DATABASE_URL:-postgresql+asyncpg://postgres:postgres@db:5432/deutsch_trainer}"
export REDIS_URL="${REDIS_URL:-redis://redis:6379/0}"
export QUIZ_BANK_API_BASE_URL="${QUIZ_BANK_API_BASE_URL:-https://quiz-bank.ci.example.invalid}"
export QUIZ_BANK_EDGE_API_KEY="${QUIZ_BANK_EDGE_API_KEY:-ci-edge-key-placeholder}"
export QUIZ_BANK_CONSUMER_ID="${QUIZ_BANK_CONSUMER_ID:-ci-consumer}"
export QUIZ_BANK_CONSUMER_API_KEY="${QUIZ_BANK_CONSUMER_API_KEY:-ci-consumer-key-placeholder}"
export ADMIN_TELEGRAM_USER_IDS="${ADMIN_TELEGRAM_USER_IDS:-1}"
export POSTGRES_USER="${POSTGRES_USER:-postgres}"
export POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-ci-postgres-password}"
export POSTGRES_DB="${POSTGRES_DB:-deutsch_trainer}"
export PUBLIC_DOMAIN="${PUBLIC_DOMAIN:-ci.example.invalid}"
export ACME_EMAIL="${ACME_EMAIL:-ops@example.invalid}"

echo "[docker_ci_check] validating default compose config"
docker compose -f docker-compose.yml config --quiet

echo "[docker_ci_check] validating dev compose overlay"
docker compose -f docker-compose.yml -f docker-compose.dev.yml config --quiet

echo "[docker_ci_check] validating production compose config"
docker compose -f docker-compose.production.yml config --quiet

echo "[docker_ci_check] building Docker image"
docker build --pull=false --tag deutsch-trainer-bot:ci .

echo "[docker_ci_check] Docker config and build checks passed"
