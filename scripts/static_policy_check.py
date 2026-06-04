#!/usr/bin/env python3
"""Verify explicit static-analysis policy until lint/type tools are configured."""

from __future__ import annotations

import subprocess
from pathlib import Path


CODE_STYLE = Path(".agent/project/CODE_STYLE.md")
PYPROJECT = Path("pyproject.toml")
SCRIPTS_DIR = Path("scripts")


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

    print("Static analysis policy check passed: lint/type tools are explicitly not configured.")
    return 0


def validate_shell_scripts() -> None:
    scripts = sorted(SCRIPTS_DIR.glob("*.sh"))
    if not scripts:
        raise SystemExit("No shell scripts found for static policy check")

    for script in scripts:
        content = script.read_text(encoding="utf-8")
        if "set -euo pipefail" not in content:
            raise SystemExit(f"{script} must enable set -euo pipefail")
        run_command(("bash", "-n", str(script)), f"{script} has invalid shell syntax")
        if '== "--help"' in content:
            run_command(("bash", str(script), "--help"), f"{script} --help failed")


def run_command(command: tuple[str, ...], error_message: str) -> None:
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        stderr = completed.stderr.strip()
        detail = f": {stderr}" if stderr else ""
        raise SystemExit(f"{error_message}{detail}")


if __name__ == "__main__":
    raise SystemExit(main())
