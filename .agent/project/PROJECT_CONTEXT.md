# PROJECT_CONTEXT

Заповни цей файл перед початком роботи агента.

Якщо обов'язкові поля лишаються незаповненими, агент має
зупинитися до початку будь-якої задачі.

## 1. Stack

- Project name: `Deutsch Trainer Bot`
- Primary languages: `Python 3.12+ for application code; Markdown for documentation; Bash for local scripts.`
- Runtime / platform: `Telegram bot backend on Python 3.12+, with polling for local development and HTTPS webhook as the locked production deployment model.`
- Main frameworks / libraries: `aiogram 3.x, SQLAlchemy 2.x async, Alembic, Pydantic Settings, httpx, asyncpg, redis client, pytest, pytest-asyncio.`
- Data stores: `PostgreSQL is the primary persistent store. Redis is available for rate limits, locks, cache, and short-lived runtime state, but not as the durable learning store.`
- Default user-facing language: `German. All bot messages, buttons, results, progress, paywall copy, recommendations, and answer explanations must be German. Deutsch Trainer Bot UI language rule: all user-facing Telegram texts must be German only. Ukrainian is allowed only in internal chat, documentation notes, or developer discussion, never in bot messages, buttons, invoices, errors, or payment labels.`

## 2. Project structure

- Root entrypoints: `app/main.py` starts the bot runtime; `alembic.ini` and `alembic/env.py` control migrations; `Dockerfile`, `docker-compose.yml`, and `docker-compose.dev.yml` define container runtime.
- Source directories: `app/` contains bot handlers/keyboards/routers, config, logging, db models/session, repositories, services, Quiz Bank client, analytics/security placeholders.
- Test directories: `tests/` contains pytest suites for foundation, bot handlers/keyboards/routers, DB models/schema, Quiz Bank client/schemas/service, training, progress, and mistakes/review.
- Config / infra directories: `.agent/`, `alembic/`, `scripts/`, root Docker/Compose/Caddy config files.
- Read-only or protected paths: `.agent/core/ unless the task explicitly changes the agent rule bundle.`

## 3. Key commands

| Purpose | Command | Notes |
|---|---|---|
| Install dev deps | `python -m pip install -e ".[dev]"` | Run inside an active virtual environment. |
| Compile | `python -m compileall app tests` | Basic Python syntax/import compilation check. |
| Test | `python -m pytest -q --capture=no` | Main pytest suite. Runtime PostgreSQL schema tests require `DATABASE_URL` or `TEST_DATABASE_URL`. |
| Local CI | `bash scripts/local_ci.sh` | Requires active virtual environment; runs compile and pytest. |
| DB runtime check | `bash scripts/db_runtime_check.sh` | Requires active virtual environment and `DATABASE_URL` or `TEST_DATABASE_URL`. |
| Build | `docker compose build` | Requires valid non-secret environment configuration. |
| Dev / Run | `python -m app.main` | Requires runtime env vars such as `BOT_TOKEN`; use local/staging credentials only. |

## 4. External dependencies

| System / service | Purpose | Access mode | Notes |
|---|---|---|---|
| Telegram Bot API | User-facing bot interface | API token / webhook or polling | Required for all bot flows. |
| Quiz Bank API | Source of quiz content | Protected HTTP API client with API keys | Bot must not duplicate the question bank. |
| Telegram Stars | Plus and Pro payments | Telegram payment flow / provider events | Prices, durations, and final package values remain decision-required before payment implementation. |
| Product analytics / admin metrics | Activation, retention, learning value, monetization metrics | PostgreSQL `analytics_events` and owner-only admin commands per architecture lock | Full implementation remains later milestone work. |
| PostgreSQL | Durable product data | `DATABASE_URL` via runtime environment | Primary data store for users, sessions, answers, progress, mistakes, subscriptions, payments, analytics. |
| Redis | Rate limits, locks, cache, short runtime state | `REDIS_URL` via runtime environment | Must not become the durable learning data store. |

## 5. Project constraints

- Protected paths: `.agent/core/ is normative; change only on explicit rule-bundle tasks. Do not modify unrelated root legacy normative files.`
- Secrets / credentials locations: `Runtime environment only; .env and local env files are gitignored. Do not commit or print Telegram tokens, Quiz Bank API keys, payment credentials, database URLs with credentials, backup credentials, or admin secrets.`
- Deploy / production boundaries: `Locked production direction is Hetzner VPS + Docker Compose + Caddy + HTTPS webhook, but no deploy or production action is allowed without an explicit user request and production checklist.`
- Approval-required operations: `Changing the locked stack/framework/database/deployment model, adding or updating dependencies, adding migrations/schema, configuring payments, deploys, production changes, destructive DB operations, and git push.`
- Restricted hosts / environments: `Production Telegram bot, production Quiz Bank API, production Telegram Stars/payment configuration, production PostgreSQL, production Redis, backup storage, and admin surfaces. Exact hostnames are not committed here.`
- Project-specific forbidden actions: `Do not duplicate Quiz Bank content inside the bot. Do not show Ukrainian or English copy in the user-facing learning interface. Do not invent paid-plan behavior outside the product vision. Do not change product strategy without explicit request.`

## 6. Git settings

- Default / protected branch: `main`
- Branching strategy: `Work on feature branches for code changes; do not push directly to main.`
- Merge strategy: `Not selected yet. Ask before merge, squash, or rebase.`
- PR title format: `Conventional Commits style, for example docs: add product vision`
- PR requirements: `Describe scope, changed files, checks run, and unresolved risks.`
