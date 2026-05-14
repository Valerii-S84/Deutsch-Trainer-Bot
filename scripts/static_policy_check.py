#!/usr/bin/env python3
"""Verify explicit static-analysis policy until lint/type tools are configured."""

from __future__ import annotations

from pathlib import Path


CODE_STYLE = Path(".agent/project/CODE_STYLE.md")
PYPROJECT = Path("pyproject.toml")


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

    print("Static analysis policy check passed: lint/type tools are explicitly not configured.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
