from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path


SCRIPT_PATH = Path("scripts/qa_release_gates.py")


def load_gate_module():
    spec = importlib.util.spec_from_file_location("qa_release_gates_for_tests", SCRIPT_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_release_gate_plan_covers_required_categories() -> None:
    module = load_gate_module()

    module.validate_gate_plan(module.GATES)
    covered = {category for gate in module.GATES for category in gate.categories}

    assert set(module.REQUIRED_CATEGORIES) <= covered


def test_release_gate_commands_reference_existing_paths() -> None:
    module = load_gate_module()

    referenced_paths = [
        path
        for gate in module.GATES
        for path in module.command_paths(gate.command)
    ]

    assert referenced_paths
    assert all((module.ROOT / path).exists() for path in referenced_paths)


def test_release_gate_check_plan_cli_passes() -> None:
    completed = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), "--check-plan"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0
    assert "QA gate plan is valid" in completed.stdout


def test_partial_gate_evidence_is_blocked() -> None:
    module = load_gate_module()
    result = make_gate_result(module, module.GATES[0], result="passed")

    report = module.build_evidence_report(
        [result],
        environment="local",
        known_risks=(),
    )

    assert report["result"] == "blocked"
    assert report["release_blocked"] is True
    assert report["gate_coverage"] == "partial"
    assert report["missing_gate_ids"]


def test_failed_gate_requires_owner_acceptance_to_unblock_release() -> None:
    module = load_gate_module()
    results = [
        make_gate_result(module, gate, result="failed" if gate.gate_id == "secret-scan" else "passed")
        for gate in module.GATES
    ]

    failed_report = module.build_evidence_report(results, environment="ci", known_risks=())
    accepted_report = module.build_evidence_report(
        results,
        environment="ci",
        known_risks=(),
        owner_acceptance={"accepted_by": "Tech owner", "reason": "Documented temporary release risk"},
    )

    assert failed_report["result"] == "failed"
    assert failed_report["release_blocked"] is True
    assert accepted_report["result"] == "accepted_with_failures"
    assert accepted_report["release_blocked"] is False
    assert accepted_report["failed_cases"] == ["secret-scan"]


def test_evidence_redacts_sensitive_output() -> None:
    module = load_gate_module()
    telegram_token = "1234567890:" + "ABCDEFGHIJKLM" + "NOPQRSTUVWXYZabcdefghi"
    bearer_token = "abcdefghijkl" + "mnopqrstuvwxyz"

    redacted = module.redact_sensitive_output(
        "tok" + "en='" + telegram_token + "' "
        "DATABASE_URL=postgresql+asyncpg://user:password@localhost/db "
        "Authorization: Bearer " + bearer_token
    )

    assert "1234567890:" not in redacted
    assert "password@localhost" not in redacted
    assert "abcdefghijklmnopqrstuvwxyz" not in redacted
    assert module.REDACTED in redacted


def make_gate_result(module, gate, *, result: str):
    return module.GateResult(
        gate_id=gate.gate_id,
        scope=gate.scope,
        command=gate.command,
        critical=gate.critical,
        result=result,
        returncode=0 if result == "passed" else 1,
        duration_seconds=0.01,
        stdout_tail="",
        stderr_tail="",
    )
