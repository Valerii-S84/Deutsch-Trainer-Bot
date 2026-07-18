#!/usr/bin/env python3
"""Validate non-secret Telegram Stars sandbox evidence JSON."""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime
from pathlib import Path


REQUIRED_TRUE_FIELDS = (
    "invoice_created",
    "invoice_payload_matches_expected_format",
    "pre_checkout_received",
    "pre_checkout_payload_matched_payment",
    "pre_checkout_answered_ok",
    "successful_payment_received",
    "successful_payment_payload_matched_payment",
    "telegram_payment_charge_id_received",
    "subscription_credited",
    "active_subscription_verified",
    "duplicate_event_rejected",
    "duplicate_event_no_second_credit",
    "duplicate_event_no_second_subscription_period",
)
REQUIRED_TEXT_FIELDS = (
    "environment",
    "tested_at",
    "telegram_bot_username",
    "telegram_stars_mode",
    "evidence_owner",
    "invoice_payload_prefix",
    "invoice_payload_format",
    "invoice_payload_sha256",
    "telegram_payment_charge_id_sha256",
    "credited_plan",
    "payment_status_after_success",
    "subscription_status_after_credit",
)
SHA256_RE = re.compile(r"^[a-f0-9]{64}$")
FORBIDDEN_RAW_FIELDS = {
    "bot_token",
    "database_url",
    "db_url",
    "invoice_payload",
    "provider_payment_charge_id",
    "raw_provider_data",
    "redis_url",
    "runtime_env",
    "telegram_payment_charge_id",
}
SECRET_PATTERNS = (
    re.compile(r"\b\d{8,12}:[A-Za-z0-9_-]{35,}\b"),
    re.compile(r"(?i)\b(api[_-]?key|token|secret|password|credential)\b\s*[:=]\s*['\"]?[^'\"\s]{8,}"),
    re.compile(r"postgresql(?:\+asyncpg)?://[^\s'\"\)]+"),
    re.compile(r"redis://[^\s'\"\)]+"),
)


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if len(args) != 1:
        raise SystemExit("Usage: python scripts/payment_sandbox_evidence_check.py <evidence.json>")

    path = Path(args[0])
    if not path.is_file():
        raise SystemExit("Payment sandbox evidence file is missing")

    payload_text = path.read_text(encoding="utf-8")
    if contains_secret_like_value(payload_text):
        raise SystemExit("Payment sandbox evidence contains secret-like values")

    payload = json.loads(payload_text)
    validate_no_forbidden_raw_fields(payload)
    validate_text_fields(payload)
    validate_true_fields(payload)
    validate_payment_observations(payload)
    validate_timestamp(payload["tested_at"])

    if payload["telegram_stars_mode"] != "test":
        raise SystemExit("telegram_stars_mode must be test for sandbox evidence")

    print("[payment_sandbox_evidence_check] Telegram Stars sandbox evidence passed")
    return 0


def validate_text_fields(payload: dict[str, object]) -> None:
    for field in REQUIRED_TEXT_FIELDS:
        value = payload.get(field)
        if not isinstance(value, str) or not value.strip():
            raise SystemExit(f"{field} must be a non-empty string")


def validate_true_fields(payload: dict[str, object]) -> None:
    for field in REQUIRED_TRUE_FIELDS:
        if payload.get(field) is not True:
            raise SystemExit(f"{field} must be true")


def validate_no_forbidden_raw_fields(payload: object, *, path: str = "$") -> None:
    if isinstance(payload, dict):
        for key, value in payload.items():
            if str(key).lower() in FORBIDDEN_RAW_FIELDS:
                raise SystemExit(f"{path}.{key} must not contain raw payment or credential data")
            validate_no_forbidden_raw_fields(value, path=f"{path}.{key}")
    elif isinstance(payload, list):
        for index, item in enumerate(payload):
            validate_no_forbidden_raw_fields(item, path=f"{path}[{index}]")


def validate_payment_observations(payload: dict[str, object]) -> None:
    if payload["invoice_payload_prefix"] != "dtbpay":
        raise SystemExit("invoice_payload_prefix must be dtbpay")
    if payload["invoice_payload_format"] != "dtbpay:{payment_id}:{idempotency_key}":
        raise SystemExit("invoice_payload_format must be dtbpay:{payment_id}:{idempotency_key}")
    if payload["credited_plan"] not in {"plus", "pro"}:
        raise SystemExit("credited_plan must be plus or pro")
    if payload["payment_status_after_success"] != "credited":
        raise SystemExit("payment_status_after_success must be credited")
    if payload["subscription_status_after_credit"] != "active":
        raise SystemExit("subscription_status_after_credit must be active")
    for field in ("invoice_payload_sha256", "telegram_payment_charge_id_sha256"):
        if not SHA256_RE.fullmatch(payload[field]):
            raise SystemExit(f"{field} must be a SHA-256 hex digest")


def validate_timestamp(raw_value: str) -> None:
    value = raw_value.replace("Z", "+00:00")
    try:
        datetime.fromisoformat(value)
    except ValueError as exc:
        raise SystemExit("tested_at must be ISO-8601") from exc


def contains_secret_like_value(value: str) -> bool:
    return any(pattern.search(value) for pattern in SECRET_PATTERNS)


if __name__ == "__main__":
    raise SystemExit(main())
