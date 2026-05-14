# Milestone 2 — PostgreSQL Runtime Verification

## Status

- Runtime verification on PostgreSQL is **blocked in current environment**.

## What was attempted

- Checked tooling:
  - `which docker.exe` → available at `C:\Program Files\Docker\Docker\resources\bin\docker.exe`
  - `docker` (WSL path) → not functional in WSL shell (`command could not be found`)
- Attempted compose start:
  - `docker.exe compose -f docker-compose.yml up -d db`
  - failed: pipe `dockerDesktopLinuxEngine` not available (`open //./pipe/dockerDesktopLinuxEngine: The system cannot find the file specified`)
- Attempted direct Alembic checks from active venv:
  - `alembic upgrade head`
  - `alembic current`
  - `alembic check`
  - all failed with PostgreSQL connection error: `Connect call failed ('127.0.0.1', 5432)`

## Runtime check script

- Added: `scripts/db_runtime_check.sh`
- Script behavior:
  - requires active venv (`VIRTUAL_ENV` or `CONDA_PREFIX`)
  - requires `DATABASE_URL` or `TEST_DATABASE_URL`
  - runs:
    - `alembic upgrade head`
    - `alembic current`
    - `alembic check`
    - schema assertions against PostgreSQL (`users`, `quiz_sessions`, `user_answers`, `progress`, `mistakes`, `subscriptions`, `payments`, `analytics_events`)
    - checks expected indexes, unique constraints, partial unique index on unresolved mistakes
    - checks JSONB column types for expected fields

## Pending commands (after environment unblocked)

1. `cd "/mnt/c/Users/User/Desktop/Deutsch Trainer Bot"`
2. `source .venv/bin/activate`
3. Choose DB URL:
   - `export DATABASE_URL=<postgresql+asyncpg://...>` or
   - `export TEST_DATABASE_URL=<postgresql+asyncpg://...>`
4. `bash scripts/db_runtime_check.sh`
5. `python3 -m pytest -q tests/test_db_runtime_schema.py`
6. `bash scripts/local_ci.sh`

## Blocker note

- Milestone 2 is **not marked complete** until a PostgreSQL runtime endpoint is reachable in the active environment and the commands above are executed successfully.

