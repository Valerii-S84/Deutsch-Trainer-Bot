PYTHON ?= python3
VENV_DIR ?= .venv
.RECIPEPREFIX = >

.PHONY: deps compile test static secret security structure check

deps:
>$(PYTHON) -m pip install --upgrade pip
>$(PYTHON) -m pip install -e ".[dev]"

compile:
>$(PYTHON) -m compileall app tests

test:
>$(PYTHON) -m pytest -q --capture=no --cov=app --cov-report=term-missing

static:
>$(PYTHON) scripts/qa_release_gates.py --check-plan
>$(PYTHON) scripts/static_policy_check.py

secret:
>$(PYTHON) scripts/secret_scan.py

security:
>$(PYTHON) scripts/security_audit.py

structure:
>$(PYTHON) scripts/structure_limits.py

check: deps compile static secret security structure test
