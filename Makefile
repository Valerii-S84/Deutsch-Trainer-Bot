PYTHON ?= python3
VENV_DIR ?= .venv
.RECIPEPREFIX = >

.PHONY: deps compile test check

deps:
>$(PYTHON) -m pip install -e ".[dev]"

compile:
>$(PYTHON) -m compileall app tests

test:
>$(PYTHON) -m pytest -q --capture=no

check: deps compile test
