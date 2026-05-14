#!/usr/bin/env bash

set -euo pipefail

if [[ -z "${VIRTUAL_ENV:-}" ]]; then
  echo "No active virtual environment detected." >&2
  echo "Create and activate one before running checks, for example:" >&2
  echo "  python3 -m venv .venv" >&2
  echo "  . .venv/bin/activate" >&2
  exit 1
fi

python -m compileall app tests
python -m pytest -q --capture=no
