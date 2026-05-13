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

## Foundation runbook

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

5. Run foundation tests:

```bash
pytest
```

## Security notes

- Secrets must be supplied through env.
- No real secrets are stored in repository files.
- `.env` is ignored by git.

