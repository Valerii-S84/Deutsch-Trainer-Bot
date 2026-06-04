# 17. Foundation Setup

## Milestone 1 status

This milestone sets up a production-oriented code foundation and does not include quiz/business logic.

## What is included

- Environment configuration via `app/config.py` with env-only settings.
- Logging with basic secret redaction in `app/logging_config.py`.
- Minimal async DB session factory in `app/db/session.py`.
- Alembic scaffold for PostgreSQL migrations.
- Docker runtime with:
  - bot service,
  - PostgreSQL,
  - Redis,
  - Caddy (HTTPS webhook entrypoint).
- Foundation test suite in `tests/test_foundation.py`.
- CI/local checks for compile, explicit lint/type policy, tracked-file secret scan and pytest.

## Foundation runbook

### Why venv-only checks

System Python in this environment is not the target for project verification.
Tests and checks are intended to run in an isolated virtual environment (or CI)
so dependencies are reproducible and no system-level Python policy (for example,
`externally managed environment`) can block local checks.

### Local verification in venv

```bash
# 1) Create isolated environment
python3 -m venv .venv

# 2) Activate it
. .venv/bin/activate

# 3) Install project + dev dependencies
python -m pip install -e ".[dev]"

# 4) Run local checks
bash scripts/local_ci.sh

# Or use make check
make check
```

### Baseline runtime setup

1. Copy environment template:

```bash
cp .env.example .env
```

2. Fill only environment variables (do not hardcode secrets in code).
3. Build images and start services:

```bash
docker compose up --build
```

4. For local dev:

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build
```

## Security notes

- Secrets must be supplied through env.
- No real secrets are stored in repository files.
- `.env` is ignored by git.
- `scripts/secret_scan.py` scans tracked files only and reports file/rule locations without printing matched secret values.

## Static analysis policy

- Python lint and type check tools are explicitly not configured yet in `.agent/project/CODE_STYLE.md`.
- Until a real toolchain is selected, CI runs `scripts/static_policy_check.py` to ensure this remains an explicit policy rather than an omitted check.
