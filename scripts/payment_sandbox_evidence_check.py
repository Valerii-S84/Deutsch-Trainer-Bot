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
    "pre_checkout_received",
    "successful_payment_received",
    "subscription_credited",
    "duplicate_event_rejected",
)
REQUIRED_TEXT_FIELDS = (
    "environment",
    "tested_at",
    "telegram_bot_username",
    "telegram_stars_mode",
    "evidence_owner",
)
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
    payload_text = path.read_text(encoding="utf-8")
    if contains_secret_like_value(payload_text):
        raise SystemExit("Payment sandbox evidence contains secret-like values")

    payload = json.loads(payload_text)
    validate_text_fields(payload)
    validate_true_fields(payload)
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
