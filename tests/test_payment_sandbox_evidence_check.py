from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


SCRIPT_PATH = Path("scripts/payment_sandbox_evidence_check.py")


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
    evidence_path.write_text(
        json.dumps(
            {
                "environment": "staging",
                "tested_at": "2026-06-05T12:00:00Z",
                "telegram_bot_username": "staging_bot",
                "telegram_stars_mode": "test",
                "evidence_owner": "QA",
                "invoice_created": True,
                "pre_checkout_received": True,
                "successful_payment_received": True,
                "subscription_credited": True,
                "duplicate_event_rejected": True,
            },
        ),
        encoding="utf-8",
    )

    completed = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), str(evidence_path)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0
    assert "Telegram Stars sandbox evidence passed" in completed.stdout
