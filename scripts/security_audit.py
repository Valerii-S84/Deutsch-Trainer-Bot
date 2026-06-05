#!/usr/bin/env python3
"""Run dependency and application security tooling for CI gates."""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from importlib.util import find_spec
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
IGNORED_DEPENDENCY_VULNS = {
    "CVE-2026-34993": "Latest aiogram 3.28.2 requires aiohttp<3.14; remove when aiogram allows aiohttp>=3.14.",
    "CVE-2026-47265": "Latest aiogram 3.28.2 requires aiohttp<3.14; remove when aiogram allows aiohttp>=3.14.",
}


@dataclass(frozen=True)
class AuditCommand:
    name: str
    command: tuple[str, ...]


AUDIT_COMMANDS = (
    AuditCommand("aiohttp-cve-runtime", ()),
    AuditCommand("dependency-audit", ()),
    AuditCommand(
        "bandit",
        (
            sys.executable,
            "-m",
            "bandit",
            "-q",
            "-r",
            "app",
        ),
    ),
)


def main() -> int:
    failed: list[str] = []
    for audit in AUDIT_COMMANDS:
        print(f"[security_audit] running {audit.name}")
        if audit.name == "aiohttp-cve-runtime":
            if not aiohttp_cve_runtime_safe():
                failed.append(audit.name)
            continue

        command = dependency_audit_command() if audit.name == "dependency-audit" else audit.command
        completed = subprocess.run(command, cwd=ROOT, text=True, check=False)
        if completed.returncode != 0:
            failed.append(audit.name)

    if failed:
        print(f"[security_audit] failed checks: {', '.join(failed)}", file=sys.stderr)
        return 1

    print("[security_audit] dependency and Bandit checks passed")
    return 0


def dependency_audit_command() -> tuple[str, ...]:
    command = [
        sys.executable,
        "-m",
        "pip_audit",
        "--local",
        "--skip-editable",
        "--progress-spinner",
        "off",
    ]
    for vulnerability_id, reason in sorted(IGNORED_DEPENDENCY_VULNS.items()):
        print(f"[security_audit] ignoring {vulnerability_id}: {reason}")
        command.extend(("--ignore-vuln", vulnerability_id))
    return tuple(command)


def aiohttp_cve_runtime_safe() -> bool:
    scan_roots = [ROOT / "app"]
    aiogram_client = aiogram_client_path()
    if aiogram_client is not None:
        scan_roots.append(aiogram_client)

    findings: list[str] = []
    for root in scan_roots:
        for path in sorted(root.rglob("*.py")):
            content = path.read_text(encoding="utf-8")
            if "CookieJar" in content:
                findings.append(f"{path}: CookieJar usage would re-open CVE-2026-34993 review")
            if ".load(" in content:
                findings.append(f"{path}: .load( usage requires CVE-2026-34993 review")
            if "cookies=" in content or "cookies =" in content:
                findings.append(f"{path}: per-request cookies= would re-open CVE-2026-47265 review")

    if findings:
        print("[security_audit] aiohttp CVE runtime check failed:", file=sys.stderr)
        print("\n".join(findings), file=sys.stderr)
        return False

    print("[security_audit] aiohttp CVE runtime check passed")
    return True


def aiogram_client_path() -> Path | None:
    spec = find_spec("aiogram")
    if spec is None or spec.origin is None:
        print("[security_audit] aiogram package not importable for aiohttp CVE runtime check", file=sys.stderr)
        return None
    return Path(spec.origin).resolve().parent / "client"


if __name__ == "__main__":
    raise SystemExit(main())
