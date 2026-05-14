# CODE_STYLE

Заповнюй тільки мовно-специфічні правила цього репозиторію.

Не дублюй тут правила з `.agent/core/PRINCIPLES.md`.
Невикористані секції позначай як `Not used in this repo.`

primary_language: `Python 3.12+`
active_sections: `Python, SQL/Alembic, Shell, Tests and fixtures, Markdown documentation`
fallback: якщо для конкретного інструмента правило не визначене,
дотримуйся існуючого стилю файлу і не додавай новий toolchain без
прямого scope задачі.

## Active languages

- Languages in scope: `Python 3.12+, SQL/Alembic migrations, Bash scripts, Markdown documentation.`

## Python

- Formatter: `No formatter is configured yet. Preserve local style; do not mass-format unrelated files.`
- Linter: `No linter is configured yet. Do not introduce or require a linter without explicit scope.`
- Type checker: `No type checker is configured yet. Keep type hints consistent with existing code and avoid untyped public service contracts when editing related code.`
- Import/order rules: `Use existing pattern: __future__ import first, then standard library, third-party imports, and app imports. Avoid unused imports.`
- Line length / docstring limits: `Keep production code readable and consistent with existing files. Avoid long functions beyond .agent/core/PRINCIPLES.md numeric limits unless covered by an allowed exception.`
- Python-specific test rules: `Use pytest and pytest-asyncio. Prefer explicit fakes/mocks for Telegram, Quiz Bank, and repositories. Do not use real Telegram, Quiz Bank, payment, or production DB credentials in tests.`

## JavaScript / TypeScript

- Formatter: `Not used in this repo.`
- Linter: `Not used in this repo.`
- Module / import conventions: `Not used in this repo.`
- Types / strictness rules: `Not used in this repo.`
- Frontend / build conventions: `Not used in this repo.`
- JS/TS-specific test rules: `Not used in this repo.`

## Go

- Formatter: `Not used in this repo.`
- Linter: `Not used in this repo.`
- Package layout rules: `Not used in this repo.`
- Error handling conventions: `Not used in this repo.`
- Go-specific test rules: `Not used in this repo.`

## SQL

- Migration conventions: `Alembic migrations live in alembic/versions/. SQLAlchemy models and migrations must stay aligned. Schema changes require migration and runtime PostgreSQL verification.`
- Query style / naming rules: `Use SQLAlchemy 2.x async patterns for app code. Raw SQL is acceptable in tests/scripts for schema inspection when parameterized.`
- DDL / DML safety rules: `Use transactions, scoped WHERE clauses for writes, and non-destructive verification by default. Destructive or production DB operations require explicit approval.`

## Shell / CLI

- Shell dialect: `Bash for scripts in scripts/.`
- Formatting / linting: `No shell linter is configured yet. Keep scripts short, readable, and consistent with existing scripts.`
- Script safety rules: `Use set -euo pipefail for executable scripts. Do not print secrets or run production/deploy/destructive commands without explicit request.`

## Tests and fixtures

- Test frameworks: `pytest, pytest-asyncio.`
- Fixture / mock conventions: `Use small explicit fixtures/fakes. Test data must contain no real secrets, real payment credentials, real personal data, or production Quiz Bank dumps.`
- Required test suites before close-out: `For Python code changes, run . .venv/bin/activate && bash scripts/local_ci.sh when available. For DB/migration changes, also run alembic/runtime PostgreSQL checks with DATABASE_URL or TEST_DATABASE_URL. For documentation-only changes, reread changed files and check that no template placeholders or project-context contradictions remain.`

## Framework or repo-specific exceptions

- `Architecture Lock in docs/16_architecture_lock.md is the source of truth for selected stack decisions. CODE_STYLE describes how to work inside that locked stack; it does not authorize changing the stack.`
