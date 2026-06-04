#!/usr/bin/env python3
"""Run Milestone 13 release QA gates and optionally write JSON evidence."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_TAIL_CHARS = 6000
REDACTED = "[REDACTED]"

REQUIRED_CATEGORIES = (
    "progress-logic",
    "answer-progress-mistake-analytics",
    "telegram-flows",
    "api-contract",
    "api-failures",
    "payments",
    "subscriptions",
    "mistakes",
    "security",
    "german-copy",
    "regression",
    "release-evidence",
)

DEFAULT_KNOWN_RISKS = (
    "Local QA gates do not prove live Telegram Stars, staging webhook, production Quiz Bank, or production deployment evidence.",
)

SECRET_PATTERNS = (
    re.compile(r"\b\d{8,12}:[A-Za-z0-9_-]{35,}\b"),
    re.compile(r"(?i)\b(bearer\s+)[A-Za-z0-9._~+/=-]{12,}"),
    re.compile(r"(?i)\b(authorization\s*[:=]\s*)[^\s]+"),
    re.compile(r"(?i)\b(api[_-]?key|token|secret|password|credential)\b\s*[:=]\s*['\"]?[^'\"\s]{8,}"),
    re.compile(r"postgresql(?:\+asyncpg)?://[^\s'\"\)]+"),
    re.compile(
        r"-----BEGIN (?:RSA |EC |OPENSSH |)PRIVATE KEY-----.*?-----END (?:RSA |EC |OPENSSH |)PRIVATE KEY-----",
        re.DOTALL,
    ),
)


@dataclass(frozen=True)
class Gate:
    gate_id: str
    scope: str
    command: tuple[str, ...]
    categories: tuple[str, ...]
    critical: bool = True


@dataclass(frozen=True)
class GateResult:
    gate_id: str
    scope: str
    command: tuple[str, ...]
    critical: bool
    result: str
    returncode: int
    duration_seconds: float
    stdout_tail: str
    stderr_tail: str


GATES = (
    Gate(
        "python-integrity",
        "Compile application, tests, and QA scripts.",
        ("{python}", "-m", "compileall", "app", "tests", "scripts"),
        ("release-evidence",),
    ),
    Gate(
        "static-policy",
        "Verify explicit lint/type policy until tools are configured.",
        ("{python}", "scripts/static_policy_check.py"),
        ("release-evidence",),
    ),
    Gate(
        "secret-scan",
        "Scan tracked files for committed secrets.",
        ("{python}", "scripts/secret_scan.py"),
        ("security", "release-evidence"),
    ),
    Gate(
        "progress-logic",
        "Progress formulas, topic state, coverage, stability, weakness, recency, and recommendations.",
        (
            "{python}",
            "-m",
            "pytest",
            "-q",
            "--capture=no",
            "tests/test_progress_model.py",
            "tests/test_progress_service.py",
            "tests/test_progress_repository.py",
            "tests/test_training_progress_integration.py",
        ),
        ("progress-logic",),
    ),
    Gate(
        "answer-to-analytics-flow",
        "Answer to progress to mistake to analytics integration paths.",
        (
            "{python}",
            "-m",
            "pytest",
            "-q",
            "--capture=no",
            "tests/test_training_session_lifecycle.py",
            "tests/test_training_session_answer_flow.py",
            "tests/test_training_session_api_limits.py",
            "tests/test_training_progress_integration.py",
            "tests/test_training_mistakes_integration.py",
            "tests/test_analytics_service.py",
        ),
        ("answer-progress-mistake-analytics", "mistakes"),
    ),
    Gate(
        "telegram-flows",
        "Telegram handlers, buttons, paywall, progress, review, subscription, and payment flows.",
        (
            "{python}",
            "-m",
            "pytest",
            "-q",
            "--capture=no",
            "tests/test_bot_handlers.py",
            "tests/test_bot_keyboards.py",
            "tests/test_quiz_keyboards.py",
            "tests/test_training_handlers.py",
            "tests/test_review_handlers.py",
            "tests/test_profile_handlers.py",
            "tests/test_subscription_handlers.py",
            "tests/test_payment_handlers.py",
            "tests/test_bot_routers.py",
        ),
        ("telegram-flows", "payments", "subscriptions", "mistakes"),
    ),
    Gate(
        "quiz-bank-contract-failures",
        "Quiz Bank client, schema contract, validation, timeout, retry, and unavailable-content behavior.",
        (
            "{python}",
            "-m",
            "pytest",
            "-q",
            "--capture=no",
            "tests/test_quiz_bank_client.py",
            "tests/test_quiz_bank_schemas.py",
            "tests/test_quiz_bank_service.py",
        ),
        ("api-contract", "api-failures"),
    ),
    Gate(
        "payment-subscription",
        "Payment idempotency, mismatch rejection, paid access, subscription lifecycle, and limits.",
        (
            "{python}",
            "-m",
            "pytest",
            "-q",
            "--capture=no",
            "tests/test_entitlements_service.py",
            "tests/test_payments_service.py",
            "tests/test_payment_handlers.py",
            "tests/test_subscription_handlers.py",
        ),
        ("payments", "subscriptions"),
    ),
    Gate(
        "security-abuse",
        "Ownership, admin access, rate limits, duplicate guards, model constraints, and safe defaults.",
        (
            "{python}",
            "-m",
            "pytest",
            "-q",
            "--capture=no",
            "tests/test_security_controls.py",
            "tests/test_admin_handlers.py",
            "tests/test_db_models.py",
            "tests/test_foundation.py",
        ),
        ("security",),
    ),
    Gate(
        "german-copy",
        "German-only user-facing copy checks.",
        ("{python}", "-m", "pytest", "-q", "--capture=no", "tests/test_german_copy.py"),
        ("german-copy",),
    ),
    Gate(
        "qa-gate-runner",
        "Release gate registry and evidence contract checks.",
        ("{python}", "-m", "pytest", "-q", "--capture=no", "tests/test_qa_release_gates.py"),
        ("release-evidence",),
    ),
    Gate(
        "release-regression",
        "Full pytest regression suite.",
        ("{python}", "-m", "pytest", "-q", "--capture=no"),
        ("regression",),
    ),
)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    selected_gates = select_gates(args.gate)

    try:
        validate_gate_plan(GATES)
        evidence_path = resolve_evidence_path(args.evidence_file) if args.evidence_file else None
    except ValueError as exc:
        print(f"QA gate plan failed: {exc}", file=sys.stderr)
        return 2

    if args.list:
        print_gate_list(selected_gates)
        return 0
    if args.check_plan:
        print(f"QA gate plan is valid: {len(GATES)} gates cover {len(REQUIRED_CATEGORIES)} categories.")
        return 0

    results = run_gates(selected_gates, fail_fast=args.fail_fast)
    report = build_evidence_report(
        results,
        environment=args.environment,
        known_risks=tuple(args.known_risk) or DEFAULT_KNOWN_RISKS,
        owner_acceptance=owner_acceptance(args),
    )
    if evidence_path is not None:
        write_evidence(evidence_path, report)
        print(f"QA evidence written: {evidence_path.relative_to(ROOT)}")

    print_summary(results, report)
    return 0 if report["release_blocked"] is False else 1


def parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-plan", action="store_true", help="Validate the gate registry without running tests.")
    parser.add_argument("--list", action="store_true", help="List selected gates without running them.")
    parser.add_argument("--gate", action="append", choices=[gate.gate_id for gate in GATES], help="Run one gate; repeatable.")
    parser.add_argument("--environment", default="local", help="Evidence environment label.")
    parser.add_argument("--evidence-file", help="Write JSON evidence to this repo-local path.")
    parser.add_argument("--known-risk", action="append", default=[], help="Known risk to include in evidence; repeatable.")
    parser.add_argument(
        "--accept-failed-critical-gates",
        action="store_true",
        help="Record explicit owner acceptance for failed critical gates.",
    )
    parser.add_argument("--accepted-by", help="Owner identity for accepted failed critical gates.")
    parser.add_argument("--acceptance-reason", help="Reason for accepting failed critical gates.")
    parser.add_argument("--fail-fast", action="store_true", help="Stop after the first failed critical gate.")
    args = parser.parse_args(argv)
    validate_acceptance_args(args)
    return args


def validate_acceptance_args(args: argparse.Namespace) -> None:
    if not args.accept_failed_critical_gates:
        return
    if not args.accepted_by or not args.acceptance_reason:
        raise SystemExit("--accepted-by and --acceptance-reason are required when accepting failed critical gates")


def select_gates(gate_ids: Sequence[str] | None) -> tuple[Gate, ...]:
    if not gate_ids:
        return GATES
    requested = set(gate_ids)
    return tuple(gate for gate in GATES if gate.gate_id in requested)


def validate_gate_plan(gates: Sequence[Gate]) -> None:
    gate_ids = [gate.gate_id for gate in gates]
    if len(gate_ids) != len(set(gate_ids)):
        raise ValueError("duplicate gate id")

    covered = {category for gate in gates for category in gate.categories}
    missing = sorted(set(REQUIRED_CATEGORIES) - covered)
    if missing:
        raise ValueError(f"missing category coverage: {', '.join(missing)}")

    for gate in gates:
        for path in command_paths(gate.command):
            if not (ROOT / path).exists():
                raise ValueError(f"{gate.gate_id} references missing path: {path}")


def command_paths(command: Sequence[str]) -> tuple[Path, ...]:
    paths: list[Path] = []
    for token in command:
        if token.startswith("-") or token in {"{python}", "pytest", "compileall"}:
            continue
        if token in {"app", "tests", "scripts"} or token.startswith(("app/", "tests/", "scripts/")):
            paths.append(Path(token))
    return tuple(paths)


def run_gates(gates: Sequence[Gate], *, fail_fast: bool) -> list[GateResult]:
    results: list[GateResult] = []
    for gate in gates:
        print(f"Running {gate.gate_id}: {gate.scope}")
        result = run_gate(gate)
        results.append(result)
        if fail_fast and gate.critical and result.result != "passed":
            break
    return results


def run_gate(gate: Gate) -> GateResult:
    command = tuple(sys.executable if token == "{python}" else token for token in gate.command)
    started = time.monotonic()
    completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=False)
    duration = time.monotonic() - started
    result = "passed" if completed.returncode == 0 else "failed"
    return GateResult(
        gate_id=gate.gate_id,
        scope=gate.scope,
        command=command,
        critical=gate.critical,
        result=result,
        returncode=completed.returncode,
        duration_seconds=round(duration, 3),
        stdout_tail=redact_sensitive_output(completed.stdout[-OUTPUT_TAIL_CHARS:]),
        stderr_tail=redact_sensitive_output(completed.stderr[-OUTPUT_TAIL_CHARS:]),
    )


def build_evidence_report(
    results: Sequence[GateResult],
    *,
    environment: str,
    known_risks: tuple[str, ...],
    owner_acceptance: dict[str, str] | None = None,
) -> dict[str, object]:
    failed_cases = [result.gate_id for result in results if result.critical and result.result != "passed"]
    executed_gate_ids = [result.gate_id for result in results]
    missing_gate_ids = [gate.gate_id for gate in GATES if gate.gate_id not in set(executed_gate_ids)]
    result_status = evidence_result(failed_cases, missing_gate_ids, owner_acceptance)
    report: dict[str, object] = {
        "test_scope": "Milestone 13 release QA gates",
        "environment": environment,
        "build_or_commit": git_commit(),
        "result": result_status,
        "release_blocked": result_status in {"blocked", "failed"},
        "gate_coverage": "full" if not missing_gate_ids else "partial",
        "expected_gate_ids": [gate.gate_id for gate in GATES],
        "executed_gate_ids": executed_gate_ids,
        "missing_gate_ids": missing_gate_ids,
        "failed_cases": failed_cases,
        "known_risks": [redact_sensitive_output(risk) for risk in known_risks],
        "tested_at": datetime.now(timezone.utc).isoformat(),
        "gate_results": [result.__dict__ for result in results],
    }
    if failed_cases and owner_acceptance:
        report["owner_acceptance"] = owner_acceptance
    return report


def evidence_result(
    failed_cases: Sequence[str],
    missing_gate_ids: Sequence[str],
    owner_acceptance: dict[str, str] | None,
) -> str:
    if missing_gate_ids:
        return "blocked"
    if failed_cases and owner_acceptance:
        return "accepted_with_failures"
    if failed_cases:
        return "failed"
    return "passed"


def owner_acceptance(args: argparse.Namespace) -> dict[str, str] | None:
    if not args.accept_failed_critical_gates:
        return None
    return {
        "accepted_by": redact_sensitive_output(args.accepted_by),
        "reason": redact_sensitive_output(args.acceptance_reason),
        "accepted_at": datetime.now(timezone.utc).isoformat(),
    }


def redact_sensitive_output(value: str) -> str:
    redacted = value
    for pattern in SECRET_PATTERNS:
        redacted = pattern.sub(lambda match: redact_match(match), redacted)
    return redacted


def redact_match(match: re.Match[str]) -> str:
    if match.lastindex:
        prefix = match.group(1) or ""
        return f"{prefix}{REDACTED}"
    return REDACTED


def git_commit() -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        return "unknown"

    commit = completed.stdout.strip()
    status = subprocess.run(
        ["git", "status", "--short"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if status.returncode == 0 and status.stdout.strip():
        return f"{commit}+dirty"
    return commit


def resolve_evidence_path(raw_path: str) -> Path:
    path = Path(raw_path)
    target = path.resolve() if path.is_absolute() else (ROOT / path).resolve()
    if target != ROOT and ROOT not in target.parents:
        raise ValueError("evidence file must stay inside the repository")
    return target


def write_evidence(path: Path, report: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def print_gate_list(gates: Sequence[Gate]) -> None:
    for gate in gates:
        print(f"{gate.gate_id}: {gate.scope}")


def print_summary(results: Sequence[GateResult], report: dict[str, object]) -> None:
    failed = [result for result in results if result.result != "passed"]
    print(f"QA gates passed: {len(results) - len(failed)}/{len(results)}")
    print(f"QA evidence result: {report['result']} (release_blocked={str(report['release_blocked']).lower()})")
    for result in failed:
        print(f"\nFAILED {result.gate_id} ({result.returncode})")
        if result.stdout_tail:
            print(result.stdout_tail)
        if result.stderr_tail:
            print(result.stderr_tail, file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
