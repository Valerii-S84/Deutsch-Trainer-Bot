#!/usr/bin/env bash

set -euo pipefail

if [[ "${1:-}" == "--help" ]]; then
  cat <<'USAGE'
Usage: SMOKE_BASE_URL=https://example.invalid bash scripts/ops_smoke.sh

Runs non-mutating smoke checks. It does not register webhooks, deploy, send
Telegram messages, create payments, or print secret values.

Optional flags through environment:
  RUN_TELEGRAM_SMOKE=1    Check Telegram getMe with BOT_TOKEN.
  RUN_QUIZ_BANK_SMOKE=1   Check Quiz Bank health path with protected headers.
  SMOKE_QUIZ_BANK_PATH    Quiz Bank health path, default /health.
USAGE
  exit 0
fi

python - <<'PY'
from __future__ import annotations

import os
import sys

import httpx


def enabled(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes"}


def require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise SystemExit(f"{name} is required")
    return value


def smoke_health(client: httpx.Client, base_url: str) -> None:
    response = client.get(f"{base_url.rstrip('/')}/health")
    if response.status_code != 200:
        raise SystemExit("Application health check failed")
    try:
        body = response.json()
    except ValueError as exc:
        raise SystemExit("Application health response is not JSON") from exc
    if body.get("status") != "ok":
        raise SystemExit("Application health status is not ok")
    print("[ops_smoke] application health passed")


def smoke_telegram(client: httpx.Client) -> None:
    token = require_env("BOT_TOKEN")
    response = client.get(f"https://api.telegram.org/bot{token}/getMe")
    if response.status_code != 200:
        raise SystemExit("Telegram getMe smoke check failed")
    payload = response.json()
    if payload.get("ok") is not True:
        raise SystemExit("Telegram getMe response was not ok")
    print("[ops_smoke] Telegram getMe passed")


def smoke_quiz_bank(client: httpx.Client) -> None:
    base_url = require_env("QUIZ_BANK_API_BASE_URL").rstrip("/")
    edge_key = os.environ.get("QUIZ_BANK_EDGE_API_KEY") or os.environ.get("QUIZ_BANK_API_KEY")
    consumer_id = require_env("QUIZ_BANK_CONSUMER_ID")
    consumer_key = require_env("QUIZ_BANK_CONSUMER_API_KEY")
    if not edge_key:
        raise SystemExit("QUIZ_BANK_EDGE_API_KEY or QUIZ_BANK_API_KEY is required")

    path = os.environ.get("SMOKE_QUIZ_BANK_PATH", "/health")
    response = client.get(
        f"{base_url}{path}",
        headers={
            "X-API-Key": edge_key,
            "X-QuizBank-API-Key": consumer_key,
            "X-Consumer-Id": consumer_id,
            "Accept": "application/json",
        },
    )
    if response.status_code not in {200, 204}:
        raise SystemExit("Quiz Bank smoke check failed")
    print("[ops_smoke] Quiz Bank smoke passed")


base_url = require_env("SMOKE_BASE_URL")
if base_url.startswith("http://") and os.environ.get("APP_ENV") != "development":
    raise SystemExit("SMOKE_BASE_URL must use HTTPS outside development")

timeout = float(os.environ.get("SMOKE_TIMEOUT_SECONDS", "10"))
try:
    with httpx.Client(timeout=timeout, follow_redirects=False) as client:
        smoke_health(client, base_url)
        if enabled("RUN_TELEGRAM_SMOKE"):
            smoke_telegram(client)
        if enabled("RUN_QUIZ_BANK_SMOKE"):
            smoke_quiz_bank(client)
except httpx.HTTPError:
    raise SystemExit("Smoke check HTTP request failed") from None

print("[ops_smoke] smoke checks finished")
PY
