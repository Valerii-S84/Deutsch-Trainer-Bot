# Implementation Roadmap Execution Log

## Мета

Виконання цього логу:
- фіксувати статус milestone/рішень з `docs/14_implementation_roadmap.md`;
- робити початок виконання строго в рамках roadmap без розширення scope;
- забезпечити прозорість блокерів перед стартом кодування.

## Поточний стан (2026-05-14)

- Виконання: Architecture Lock completed.
- Поточний статус: Milestone 0 завершено, Milestone 1 (Repository and Foundation) completed, Milestone 2 (Domain and schema planning) готовий до старту.

## Milestone 0 — Architecture Lock

### Blocking decisions (status)

Architecture Lock: **COMPLETED** (`docs/16_architecture_lock.md`)

### Закриті рішення

- Stack: Python 3.12+  
- Framework: aiogram 3.x  
- DB: PostgreSQL  
- ORM / Migrations: SQLAlchemy 2.x async + Alembic  
- Deployment model: Hetzner VPS + Docker Compose + Caddy + HTTPS webhook  
- API integration model: protected consumer integration з existing Quiz Bank API, без локального дублювання контенту  
- Payment architecture: Telegram Stars + Free/Plus/Pro model з конфігураційними тарифами  
- Security model: env-only secrets, webhook secret, no secrets in logs, API keys protected, rate limits, payment audit log  
- QA model: pytest + unit/integration/Telegram flow/Quiz Bank integration/payment-subscription-progress regression  

### Open, але не блокують Foundation

- exact Plus price (Decision Required Before Payment Implementation)
- exact Pro price (Decision Required Before Payment Implementation)
- Plus duration (Decision Required Before Payment Implementation)
- Pro duration (Decision Required Before Payment Implementation)
- final Telegram Stars package values (Decision Required Before Payment Implementation)
- final public tariff copy (Decision Required Before Payment Implementation)

### Gate

- Milestone 1 can start.  
- Milestone 2 can start after DB schema planning and migration design.

## Milestone 1 — Repository and Foundation

### Completion check (Foundation gate)

- Milestone 1 завершується лише після проходження:
  - `python3 -m venv .venv`
  - `. .venv/bin/activate`
  - `python -m pip install -e ".[dev]"`
  - `bash scripts/local_ci.sh`
- Системний Python не є цільовим середовищем для `foundation`-перевірок.
  Його падіння через `PEP 668`/`externally managed environment` не є blocker для продовження roadmap, якщо в CI/venv ці перевірки проходять.

- Верифікацію виконано для `venv/CI`:
- `python -m compileall app tests`
- `python -m pytest -q` (у `scripts/local_ci.sh` виконуються з `--capture=no` для стабільності в середовищі)

- Базову структуру створено: pyproject, Docker, app package, tests, alembic scaffold.

### Standard checks

- `bash scripts/local_ci.sh` (локально)
- `python -m pytest -q` in CI after installing `.[dev]` (локально виконується через `scripts/local_ci.sh`/`Makefile` у venv)

## Milestone 2+ — Code/migration/data work

- 2026-05-14: старт відкрито після Milestone 1, оновлено до стану базового
  data layer execution.
- 2026-05-14: виконано:
  - schema-моделі `users`, `quiz_sessions`, `user_answers`, `progress`,
    `mistakes`, `subscriptions`, `payments`, `analytics_events`;
  - початкова Alembic міграція `202605140001_initial_schema.py`;
  - оновлення логу виконання та базових тести для metadata/constraints/indexes.

## Активні ризики (витяг з roadmap, секції 19)

- exact Plus price / exact Pro price (Decision Required Before Payment Implementation)
- Plus / Pro duration (Decision Required Before Payment Implementation)
- final Telegram Stars package values
- final public tariff copy
- API payload/verification details потрібно підтвердити до фінальної payment реалізації.
- Ризик корупції стану залишається доти, доки не ввімкнено idempotency і правильне ordering transaction у наступних milestone.
- Дублювання оновлень Telegram і дублювання payment events мають бути закриті в Milestone 5/9.
- Нестабільне покриття та regressions у German copy залишаються QA-ризиками.
- Готовність backup/restore/rollback валідатиметься на Milestone 12.

## Вимоги до виконання (далі)

1. Підтвердити фінальні tariff values (`exact Plus/Pro price`, `exact Plus/Pro duration`, final Stars package values, `public tariff copy`) до початку фінальної payment імплементації.
2. Зафіксувати remaining operational config для rollout (`limits`, `cooldown`, retry/circuit settings for Quiz Bank API) в підготовчому документі/конфігурації.
3. Почати Milestone 1–13 по черзі в порядку з `docs/14_implementation_roadmap.md`.
