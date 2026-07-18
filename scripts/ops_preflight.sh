#!/usr/bin/env bash

set -euo pipefail

if [[ "${1:-}" == "--help" ]]; then
  cat <<'USAGE'
Usage: bash scripts/ops_preflight.sh

Validates repo-side deployment readiness for the current environment.
The script does not deploy, register Telegram webhooks, or print secret values.

Optional flags through environment:
  SKIP_COMPOSE_PREFLIGHT=1    Skip docker compose config validation.
  SKIP_DB_PREFLIGHT=1         Skip database connectivity check.
  SKIP_REDIS_PREFLIGHT=1      Skip Redis connectivity check.
  RUN_EXTERNAL_PREFLIGHT=1    Run scripts/ops_smoke.sh after local checks.
USAGE
  exit 0
fi

log() {
  printf '[ops_preflight] %s\n' "$1"
}

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    printf '[ops_preflight] missing command: %s\n' "$1" >&2
    exit 1
  fi
}

require_command python

log "validating application configuration"
python - <<'PY'
from __future__ import annotations

from app.config import AppEnvironment, get_settings

settings = get_settings()
settings.require_production_secrets()

if settings.app_env not in {
    AppEnvironment.staging,
    AppEnvironment.production,
}:
    raise SystemExit("APP_ENV must be staging or production for deployment preflight")
if settings.app_env != AppEnvironment.development and not settings.bot_webhook_enabled:
    raise SystemExit("Webhook mode must be enabled outside development")
if settings.app_env != AppEnvironment.development and settings.bot_polling_enabled:
    raise SystemExit("Polling mode must be disabled outside development")
if settings.app_env != AppEnvironment.development and settings.security_state_backend == "in_memory":
    raise SystemExit("SECURITY_STATE_BACKEND=in_memory is not allowed outside development")
if settings.telegram_webhook_max_connections > settings.bot_global_in_flight_limit:
    raise SystemExit("TELEGRAM_WEBHOOK_MAX_CONNECTIONS must not exceed BOT_GLOBAL_IN_FLIGHT_LIMIT")
if settings.db_pool_timeout <= 0:
    raise SystemExit("DB_POOL_TIMEOUT must be positive")

print("[ops_preflight] configuration validation passed")
PY

if [[ "${SKIP_COMPOSE_PREFLIGHT:-0}" != "1" ]]; then
  if command -v docker >/dev/null 2>&1; then
    log "validating docker compose production config"
    docker compose -f docker-compose.production.yml config --quiet
  else
    log "docker is unavailable; compose validation skipped"
  fi
fi

if [[ "${SKIP_DB_PREFLIGHT:-0}" != "1" ]]; then
  log "checking database connectivity"
  python - <<'PY'
from __future__ import annotations

import asyncio

from app.db.session import dispose_engine, measure_pool_wait_ms


async def main() -> None:
    try:
        wait_ms = await measure_pool_wait_ms()
        print(f"[ops_preflight] database connectivity passed pool_wait_ms={wait_ms:.3f}")
    finally:
        await dispose_engine()


asyncio.run(main())
PY
fi

if [[ "${SKIP_REDIS_PREFLIGHT:-0}" != "1" ]]; then
  log "checking Redis connectivity"
  python - <<'PY'
from __future__ import annotations

import asyncio

from redis.asyncio import Redis

from app.config import get_settings


async def main() -> None:
    settings = get_settings()
    client = Redis.from_url(settings.redis_url)
    try:
        await client.ping()
    finally:
        await client.aclose()


asyncio.run(main())
print("[ops_preflight] Redis connectivity passed")
PY
fi

if [[ "${RUN_EXTERNAL_PREFLIGHT:-0}" == "1" ]]; then
  log "running external smoke checks"
  bash scripts/ops_smoke.sh
fi

log "preflight finished"
