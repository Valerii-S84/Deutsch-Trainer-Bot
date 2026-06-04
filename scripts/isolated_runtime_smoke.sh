#!/usr/bin/env bash

set -euo pipefail

if [[ "${1:-}" == "--help" ]]; then
  cat <<'USAGE'
Usage: bash scripts/isolated_runtime_smoke.sh

Runs non-mutating smoke checks for the isolated Docker runtime. It does not
deploy, restart services, change environment values, register webhooks, send
Telegram messages, or print secret values.

Optional environment:
  BOT_CONTAINER       Bot container, default deutsch-trainer-bot-bot-1.
  DB_CONTAINER        DB container, default deutsch-trainer-bot-db-1.
  REDIS_CONTAINER     Redis container, default deutsch-trainer-bot-redis-1.
  LOG_SINCE           Docker logs window, default 10m.
  RUN_TELEGRAM_SMOKE  Check Telegram getMe from inside the bot container.
  PRINT_RECENT_LOGS   Print sanitized recent bot logs after scanning.
USAGE
  exit 0
fi

BOT_CONTAINER="${BOT_CONTAINER:-deutsch-trainer-bot-bot-1}"
DB_CONTAINER="${DB_CONTAINER:-deutsch-trainer-bot-db-1}"
REDIS_CONTAINER="${REDIS_CONTAINER:-deutsch-trainer-bot-redis-1}"
LOG_SINCE="${LOG_SINCE:-10m}"

log() {
  printf '[isolated_smoke] %s\n' "$1"
}

fail() {
  printf '[isolated_smoke] %s\n' "$1" >&2
  exit 1
}

enabled() {
  case "${!1:-}" in
    1|true|TRUE|yes|YES) return 0 ;;
    *) return 1 ;;
  esac
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || fail "missing command: $1"
}

container_status() {
  docker inspect "$1" --format '{{.State.Status}}' 2>/dev/null || true
}

require_running_container() {
  local container="$1"
  local status
  status="$(container_status "$container")"
  [[ "$status" == "running" ]] || fail "$container is not running"
  log "$container running"
}

sanitize_logs() {
  sed -E \
    -e 's#(https://api\.telegram\.org/bot)[^/[:space:]]+#\1***REDACTED***#Ig' \
    -e 's/(BOT_TOKEN|TELEGRAM_WEBHOOK_SECRET|QUIZ_BANK[^= ]*KEY|API_KEY|TOKEN|SECRET|PASSWORD)=([^[:space:]]+)/\1=***REDACTED***/Ig' \
    -e 's/(Authorization: Bearer )[[:alnum:]_.:-]+/\1***REDACTED***/Ig' \
    -e 's#(postgresql(\\+asyncpg)?://)[^[:space:]]+#\1***REDACTED***#Ig' \
    -e 's/\[parameters: \([^)]*\)\]/[parameters: ***REDACTED***]/g'
}

require_command docker

require_running_container "$BOT_CONTAINER"
require_running_container "$DB_CONTAINER"
require_running_container "$REDIS_CONTAINER"

log "checking required bot environment presence"
docker exec "$BOT_CONTAINER" python - <<'PY'
from __future__ import annotations

import os

required = (
    "BOT_TOKEN",
    "DATABASE_URL",
    "REDIS_URL",
    "QUIZ_BANK_API_BASE_URL",
    "QUIZ_BANK_EDGE_API_KEY",
    "QUIZ_BANK_CONSUMER_ID",
    "QUIZ_BANK_CONSUMER_API_KEY",
)
missing = []
for name in required:
    present = bool(os.environ.get(name))
    print(f"{name}={'present' if present else 'missing'}")
    if not present:
        missing.append(name)

if missing:
    raise SystemExit("required environment is missing")
PY

log "checking isolated database schema"
docker exec "$BOT_CONTAINER" python - <<'PY'
from __future__ import annotations

import asyncio
import os

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

required_tables = (
    "users",
    "quiz_sessions",
    "training_session_items",
    "user_answers",
    "progress",
    "mistakes",
    "alembic_version",
)


async def main() -> None:
    engine = create_async_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)
    try:
        async with engine.connect() as connection:
            missing = []
            for table_name in required_tables:
                exists = await connection.scalar(
                    text("SELECT to_regclass(:table_name)"),
                    {"table_name": f"public.{table_name}"},
                )
                print(f"{table_name}={'present' if exists else 'missing'}")
                if not exists:
                    missing.append(table_name)
            if missing:
                raise SystemExit("required database table is missing")
    finally:
        await engine.dispose()


asyncio.run(main())
print("db_schema=passed")
PY

log "checking Redis connectivity"
docker exec "$BOT_CONTAINER" python - <<'PY'
from __future__ import annotations

import asyncio
import os

from redis.asyncio import Redis


async def main() -> None:
    client = Redis.from_url(os.environ["REDIS_URL"])
    try:
        pong = await client.ping()
        if pong is not True:
            raise SystemExit("Redis ping failed")
    finally:
        await client.aclose()


asyncio.run(main())
print("redis_ping=passed")
PY

if enabled RUN_TELEGRAM_SMOKE; then
  log "checking Telegram getMe"
  docker exec "$BOT_CONTAINER" python - <<'PY'
from __future__ import annotations

import json
import os
from urllib.request import urlopen

token = os.environ.get("BOT_TOKEN")
if not token:
    raise SystemExit("BOT_TOKEN is missing")

with urlopen(f"https://api.telegram.org/bot{token}/getMe", timeout=10) as response:
    payload = json.loads(response.read().decode("utf-8"))

if payload.get("ok") is not True:
    raise SystemExit("Telegram getMe failed")

result = payload.get("result") or {}
username = result.get("username") or "unknown"
print(f"telegram_getme=passed username={username}")
PY
fi

log "scanning recent bot logs"
recent_logs="$(docker logs --since "$LOG_SINCE" "$BOT_CONTAINER" 2>&1 | sanitize_logs)"
if printf '%s\n' "$recent_logs" | grep -Eiq 'Traceback|CRITICAL|ERROR|relation "users" does not exist'; then
  if enabled PRINT_RECENT_LOGS; then
    printf '%s\n' "$recent_logs" | tail -n 160
  fi
  fail "recent bot logs contain an error pattern"
fi
log "recent bot logs passed"

if enabled PRINT_RECENT_LOGS; then
  printf '%s\n' "$recent_logs" | tail -n 160
fi

log "isolated runtime smoke finished"
