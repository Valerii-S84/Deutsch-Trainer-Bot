from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


SCRIPT_PATH = Path("scripts/payment_sandbox_evidence_check.py")
PAYLOAD_HASH = "a" * 64
CHARGE_HASH = "b" * 64


def test_missing_payment_evidence_file_fails_without_traceback(tmp_path: Path) -> None:
    missing_path = tmp_path / "missing.json"

    completed = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), str(missing_path)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode != 0
    assert "Payment sandbox evidence file is missing" in completed.stderr
    assert "Traceback" not in completed.stderr


def test_valid_payment_evidence_file_passes(tmp_path: Path) -> None:
    evidence_path = tmp_path / "telegram_stars_sandbox.json"
    evidence_path.write_text(json.dumps(_valid_evidence()), encoding="utf-8")

    completed = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), str(evidence_path)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0
    assert "Telegram Stars sandbox evidence passed" in completed.stdout


def test_production_vps_sandbox_evidence_passes_only_when_mode_is_test(tmp_path: Path) -> None:
    evidence = _valid_evidence()
    evidence["environment"] = "production-vps sandbox Telegram Stars test flow"
    evidence["telegram_bot_username"] = "Trainer1512_bot"
    evidence["telegram_stars_mode"] = "test"
    evidence_path = tmp_path / "telegram_stars_sandbox.json"
    evidence_path.write_text(json.dumps(evidence), encoding="utf-8")

    completed = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), str(evidence_path)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0
    assert "Telegram Stars sandbox evidence passed" in completed.stdout


def test_prod_stars_mode_fails_even_when_other_facts_pass(tmp_path: Path) -> None:
    evidence = _valid_evidence()
    evidence["telegram_stars_mode"] = "prod"
    evidence_path = tmp_path / "telegram_stars_sandbox.json"
    evidence_path.write_text(json.dumps(evidence), encoding="utf-8")

    completed = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), str(evidence_path)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode != 0
    assert "telegram_stars_mode must be test for sandbox evidence" in completed.stderr


def test_missing_charge_id_proof_fails(tmp_path: Path) -> None:
    evidence = _valid_evidence()
    evidence["telegram_payment_charge_id_received"] = False
    evidence_path = tmp_path / "telegram_stars_sandbox.json"
    evidence_path.write_text(json.dumps(evidence), encoding="utf-8")

    completed = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), str(evidence_path)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode != 0
    assert "telegram_payment_charge_id_received must be true" in completed.stderr


def test_wrong_payload_prefix_fails(tmp_path: Path) -> None:
    evidence = _valid_evidence()
    evidence["invoice_payload_prefix"] = "unexpected"
    evidence_path = tmp_path / "telegram_stars_sandbox.json"
    evidence_path.write_text(json.dumps(evidence), encoding="utf-8")

    completed = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), str(evidence_path)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode != 0
    assert "invoice_payload_prefix must be dtbpay" in completed.stderr


def test_wrong_payload_format_fails(tmp_path: Path) -> None:
    evidence = _valid_evidence()
    evidence["invoice_payload_format"] = "dtbpay:{idempotency_key}"
    evidence_path = tmp_path / "telegram_stars_sandbox.json"
    evidence_path.write_text(json.dumps(evidence), encoding="utf-8")

    completed = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), str(evidence_path)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode != 0
    assert "invoice_payload_format must be dtbpay:{payment_id}:{idempotency_key}" in completed.stderr


def test_raw_telegram_charge_id_field_fails(tmp_path: Path) -> None:
    evidence = _valid_evidence()
    evidence["telegram_payment_charge_id"] = "raw-charge-id"
    evidence_path = tmp_path / "telegram_stars_sandbox.json"
    evidence_path.write_text(json.dumps(evidence), encoding="utf-8")

    completed = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), str(evidence_path)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode != 0
    assert "telegram_payment_charge_id must not contain raw payment or credential data" in completed.stderr


def test_raw_invoice_payload_nested_field_fails(tmp_path: Path) -> None:
    evidence = _valid_evidence()
    evidence["observations"] = {"invoice_payload": "dtbpay:1:raw-key"}
    evidence_path = tmp_path / "telegram_stars_sandbox.json"
    evidence_path.write_text(json.dumps(evidence), encoding="utf-8")

    completed = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), str(evidence_path)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode != 0
    assert "invoice_payload must not contain raw payment or credential data" in completed.stderr


def test_secret_like_value_under_allowed_key_fails(tmp_path: Path) -> None:
    evidence = _valid_evidence()
    evidence["notes"] = "credential: definitelysecret"
    evidence_path = tmp_path / "telegram_stars_sandbox.json"
    evidence_path.write_text(json.dumps(evidence), encoding="utf-8")

    completed = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), str(evidence_path)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode != 0
    assert "Payment sandbox evidence contains secret-like values" in completed.stderr


def test_missing_duplicate_no_second_period_proof_fails(tmp_path: Path) -> None:
    evidence = _valid_evidence()
    evidence["duplicate_event_no_second_subscription_period"] = False
    evidence_path = tmp_path / "telegram_stars_sandbox.json"
    evidence_path.write_text(json.dumps(evidence), encoding="utf-8")

    completed = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), str(evidence_path)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode != 0
    assert "duplicate_event_no_second_subscription_period must be true" in completed.stderr


def test_uncredited_payment_status_fails(tmp_path: Path) -> None:
    evidence = _valid_evidence()
    evidence["payment_status_after_success"] = "paid"
    evidence_path = tmp_path / "telegram_stars_sandbox.json"
    evidence_path.write_text(json.dumps(evidence), encoding="utf-8")

    completed = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), str(evidence_path)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode != 0
    assert "payment_status_after_success must be credited" in completed.stderr


def test_inactive_subscription_status_fails(tmp_path: Path) -> None:
    evidence = _valid_evidence()
    evidence["subscription_status_after_credit"] = "inactive"
    evidence_path = tmp_path / "telegram_stars_sandbox.json"
    evidence_path.write_text(json.dumps(evidence), encoding="utf-8")

    completed = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), str(evidence_path)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode != 0
    assert "subscription_status_after_credit must be active" in completed.stderr


def _valid_evidence() -> dict[str, object]:
    return {
        "environment": "staging",
        "tested_at": "2026-06-05T12:00:00Z",
        "telegram_bot_username": "staging_bot",
        "telegram_stars_mode": "test",
        "evidence_owner": "QA",
        "invoice_payload_prefix": "dtbpay",
        "invoice_payload_format": "dtbpay:{payment_id}:{idempotency_key}",
        "invoice_payload_sha256": PAYLOAD_HASH,
        "telegram_payment_charge_id_sha256": CHARGE_HASH,
        "credited_plan": "plus",
        "payment_status_after_success": "credited",
        "subscription_status_after_credit": "active",
        "invoice_created": True,
        "invoice_payload_matches_expected_format": True,
        "pre_checkout_received": True,
        "pre_checkout_payload_matched_payment": True,
        "pre_checkout_answered_ok": True,
        "successful_payment_received": True,
        "successful_payment_payload_matched_payment": True,
        "telegram_payment_charge_id_received": True,
        "subscription_credited": True,
        "active_subscription_verified": True,
        "duplicate_event_rejected": True,
        "duplicate_event_no_second_credit": True,
        "duplicate_event_no_second_subscription_period": True,
    }
