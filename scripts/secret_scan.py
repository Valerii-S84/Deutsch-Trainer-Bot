#!/usr/bin/env python3
"""Minimal tracked-file secret scan for local CI and GitHub CI."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path


PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("telegram_bot_token", re.compile(r"\b\d{8,12}:[A-Za-z0-9_-]{35,}\b")),
    ("private_key_block", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |)PRIVATE KEY-----")),
    ("aws_access_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    (
        "assigned_secret",
        re.compile(
            r"(?i)\b(?:api[_-]?key|token|secret|password)\b\s*=\s*['\"][^'\"\s]{12,}['\"]",
        ),
    ),
)

SKIP_SUFFIXES = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".ico",
    ".pyc",
    ".zip",
}


def tracked_files() -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files"],
        check=True,
        capture_output=True,
        text=True,
    )
    return [Path(line) for line in result.stdout.splitlines() if line.strip()]


def scan_file(path: Path, *, allowlist: set[str] | None = None) -> list[str]:
    if path.suffix.lower() in SKIP_SUFFIXES:
        return []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except UnicodeDecodeError:
        return []

    findings: list[str] = []
    allowed_findings = allowlist or set()
    for line_number, line in enumerate(lines, start=1):
        for rule_name, pattern in PATTERNS:
            if not pattern.search(line):
                continue
            finding_key = f"{path.as_posix()}:{line_number}:{rule_name}"
            if finding_key in allowed_findings:
                continue
            findings.append(f"{path}:{line_number}: possible secret ({rule_name})")
    return findings


def main() -> int:
    findings: list[str] = []
    for path in tracked_files():
        findings.extend(scan_file(path))

    if findings:
        print("Secret scan failed:")
        print("\n".join(findings))
        return 1

    print("Secret scan passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
