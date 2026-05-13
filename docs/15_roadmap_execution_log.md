# Implementation Roadmap Execution Log

## Мета

Виконання цього логу:
- фіксувати статус milestone/рішень з `docs/14_implementation_roadmap.md`;
- робити початок виконання строго в рамках roadmap без розширення scope;
- забезпечити прозорість блокерів перед стартом кодування.

## Поточний стан (2026-05-14)

- Виконання: Architecture Lock completed.
- Поточний статус: Milestone 0 завершено, готовність до запуску Milestone 1 підтверджена.
- Наступний крок: розпочати Milestone 1 — Repository and Foundation.

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

- Може стартувати на основі `docs/16_architecture_lock.md`.

## Milestone 2+ — Code/migration/data work

- Старт відкладено до завершення Milestone 1.

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
