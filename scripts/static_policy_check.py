#!/usr/bin/env python3
"""Verify explicit static-analysis policy until lint/type tools are configured."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path


CODE_STYLE = Path(".agent/project/CODE_STYLE.md")
PYPROJECT = Path("pyproject.toml")
SCRIPTS_DIR = Path("scripts")
CI_WORKFLOW = Path(".github/workflows/ci.yml")


def main() -> int:
    code_style = CODE_STYLE.read_text(encoding="utf-8")
    pyproject = PYPROJECT.read_text(encoding="utf-8")

    required_policy = (
        "Linter: `No linter is configured yet.",
        "Type checker: `No type checker is configured yet.",
    )
    for marker in required_policy:
        if marker not in code_style:
            raise SystemExit(f"Static policy marker is missing: {marker}")

    configured_tools = ("[tool.ruff", "[tool.mypy", "[tool.pyright", "[tool.pyre")
    configured = [tool for tool in configured_tools if tool in pyproject]
    if configured:
        raise SystemExit(f"Static tools configured but not wired into CI: {', '.join(configured)}")

    validate_shell_scripts()
    validate_ci_german_copy_guard()

    print("Static analysis policy check passed: lint/type tools are explicitly not configured.")
    return 0


def validate_shell_scripts() -> None:
    scripts = sorted(SCRIPTS_DIR.glob("*.sh"))
    if not scripts:
        raise SystemExit("No shell scripts found for static policy check")

    bash = find_usable_bash()
    if bash is None:
        raise SystemExit("No executable bash found for shell script validation")

    for script in scripts:
        content = script.read_text(encoding="utf-8")
        if "set -euo pipefail" not in content:
            raise SystemExit(f"{script} must enable set -euo pipefail")
        run_command((bash, "-n", str(script)), f"{script} has invalid shell syntax")
        if '== "--help"' in content:
            run_command((bash, str(script), "--help"), f"{script} --help failed")


def validate_ci_german_copy_guard() -> None:
    workflow = CI_WORKFLOW.read_text(encoding="utf-8")
    required_markers = (
        "German-only Telegram UI guard",
        "python -m pytest -q --capture=no tests/test_german_copy.py",
    )
    for marker in required_markers:
        if marker not in workflow:
            raise SystemExit(f"CI German-only UI guard is missing: {marker}")


def run_command(command: tuple[str, ...], error_message: str) -> None:
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        stderr = completed.stderr.strip()
        detail = f": {stderr}" if stderr else ""
        raise SystemExit(f"{error_message}{detail}")


def find_usable_bash() -> str | None:
    for candidate in _bash_candidates():
        if _is_usable_bash(candidate):
            return candidate
    return None


def _bash_candidates() -> tuple[str, ...]:
    candidates: list[str] = []
    env_bash = os.environ.get("BASH")
    if env_bash:
        candidates.append(env_bash)
    path_bash = shutil.which("bash")
    if path_bash:
        candidates.append(path_bash)
    if os.name == "nt":
        candidates.extend(
            (
                r"C:\Program Files\Git\bin\bash.exe",
                r"C:\Program Files\Git\usr\bin\bash.exe",
            ),
        )
    return tuple(dict.fromkeys(candidates))


def _is_usable_bash(candidate: str) -> bool:
    try:
        completed = subprocess.run(
            (candidate, "--version"),
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return completed.returncode == 0


if __name__ == "__main__":
    raise SystemExit(main())
