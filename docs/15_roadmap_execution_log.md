# Implementation Roadmap Execution Log

## Мета

Виконання цього логу:
- фіксувати статус milestone/рішень з `docs/14_implementation_roadmap.md`;
- робити початок виконання строго в рамках roadmap без розширення scope;
- забезпечити прозорість блокерів перед стартом кодування.

## Поточний стан (2026-05-15)

- Виконання: Milestone 0-7 acceptance recovery completed against roadmap gates.
- Поточний статус: Milestone 0-7 закрито після усунення розривів між roadmap/docs/code/tests:
  Home/onboarding, Quiz Bank availability-driven themes, persisted API error logs,
  Telegram update idempotency, progress rows for available unanswered topics,
  explicit Mistake Screen before review session.

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
- 2026-05-14: додано runtime verification assets:
  - `scripts/db_runtime_check.sh`
  - `tests/test_db_runtime_schema.py`
  - `docs/19_database_runtime_verification.md`
- 2026-05-14: runtime verification completed on PostgreSQL:
  - `docker compose` доступний (`version: 28.4.0`, `context: default`).
  - `docker compose -f docker-compose.yml -f /tmp/compose-db-runtime.yml up -d db`
    (temporary runtime override with `ports: ["5433:5432"]`).
  - `docker compose -f docker-compose.yml -f /tmp/compose-db-runtime.yml ps` показав `db` up з портом `5433`.
  - `DATABASE_URL='postgresql+asyncpg://postgres:postgres@localhost:5433/deutsch_trainer'`
    `alembic upgrade head` → success.
  - `alembic current` → `202605140001 (head)`.
  - `alembic check` → `No new upgrade operations detected.`
  - `bash scripts/db_runtime_check.sh` → passed (`tables`, `indexes`, `constraints`,
    `partial unique index`, `jsonb` checks passed).
  - `python -m pytest -q tests/test_db_runtime_schema.py --capture=no` → passed (schema tests).
  - `bash scripts/local_ci.sh` → passed.
  - Confirmed DB objects:
    - Tables: `users`, `quiz_sessions`, `user_answers`, `progress`, `mistakes`,
      `subscriptions`, `payments`, `analytics_events`
    - Indexes: `ix_users_telegram_user_id`, `ix_users_language_code`, `ix_user_answers_user_id`,
      `ix_user_answers_session_id`, `ix_user_answers_external_quiz_id`, `ix_mistakes_user_id`,
      `ix_mistakes_external_quiz_id`, `ix_mistakes_active_user_external` (partial unique),
      `ix_progress_level_theme`, `ix_progress_user_id`, `ix_payments_user_id`,
      `ix_subscriptions_user_id`, `ix_subscriptions_status_expires_at`,
      `ix_analytics_events_user_id`, `ix_analytics_events_session_id`, `ix_analytics_events_event_name_time`,
      `ix_quiz_sessions_user_id`
    - Unique constraints: `uq_users_telegram_user_id`, `uq_user_answers_user_session_external_quiz`,
      `uq_progress_user_level_theme`, `uq_payments_idempotency_key`,
      `uq_payments_provider_payment_charge_id`
    - JSONB columns confirmed: `quiz_sessions.source_metadata`, `quiz_sessions.api_metadata`,
      `mistakes.source_snapshot`, `payments.audit_metadata`, `analytics_events.event_metadata`

## Milestone 0-7 Acceptance Recovery

### 2026-05-15

- Milestone 0:
  - `docs/14_implementation_roadmap.md` і `docs/16_architecture_lock.md` узгоджені для M0-7:
    Quiz Bank runtime contract/cache scope, config-driven plan limits and Plus+ mistake repeat policy
    більше не позначені як coding blockers для M0-7.
- Milestone 1:
  - CI/local checks доповнені compile, explicit lint/type policy check, tracked-file secret scan and pytest.
  - `docs/17_foundation_setup.md` описує, що lint/type tools ще не configured, а policy check робить це явним.
- Milestone 3:
  - Home має лише `▶️ Üben`, `🎯 Niveau & Thema`, `📊 Mein Fortschritt`.
  - `/start` для user without `selected_level` веде на Level Selection.
  - Review/Subscription прибрані з primary Home.
- Milestone 4:
  - Theme selection використовує Quiz Bank `get_themes(level=...)` з availability-driven list.
  - Quiz Bank API failures у training path записуються в persisted `api_error_logs`.
  - Availability count підтягується через Quiz Bank availability для progress metadata, коли endpoint доступний.
- Milestone 5:
  - `telegram_update_id` прокидається з aiogram `event_update` до `UserAnswer`.
  - Duplicate Telegram update id повертає duplicate result без другого answer/progress/mistake mutation.
- Milestone 6:
  - Progress summary може показувати available topics without answers.
  - Existing progress rows отримують `available_items_count`/coverage з Quiz Bank catalog, коли catalog доступний.
- Milestone 7:
  - `menu:review` відкриває Mistake Screen active state.
  - Review session стартує тільки з `review:start`.
  - Mistake Screen кнопки: `▶️ Fehler üben`, `📊 Mein Fortschritt`, `🏠 Hauptmenü`.

## Активні ризики (витяг з roadmap, секції 19)

- exact Plus price / exact Pro price (Decision Required Before Payment Implementation)
- Plus / Pro duration (Decision Required Before Payment Implementation)
- final Telegram Stars package values
- final public tariff copy
- API payload/verification details потрібно підтвердити до фінальної payment реалізації.
- Дублювання payment events має бути закрите в Milestone 9.
- Нестабільне покриття та regressions у German copy залишаються QA-ризиками.
- Готовність backup/restore/rollback валідатиметься на Milestone 12.

## Вимоги до виконання (далі)

1. Підтвердити фінальні tariff values (`exact Plus/Pro price`, `exact Plus/Pro duration`, final Stars package values, `public tariff copy`) до початку фінальної payment імплементації.
2. Зафіксувати remaining operational config для rollout (`limits`, `cooldown`, retry/circuit settings for Quiz Bank API) в підготовчому документі/конфігурації.
3. Почати Milestone 1–13 по черзі в порядку з `docs/14_implementation_roadmap.md`.

## Milestone 4 — Quiz Bank API Integration

### Поточний статус

`2026-05-14`: почато.

### Виконані/заплановані кроки

- додано production-ready async Quiz Bank клієнт (`app/quiz_bank/client.py`) з timeout/retry;
- додано валідаційні схеми для item/answers/explanation/source/error (`app/quiz_bank/schemas.py`);
- додано explicit errors (`app/quiz_bank/errors.py`);
- додано service layer без доступу до DB/Telegram handlers (`app/quiz_bank/service.py`);
- розширено `app/config.py` новими quiz bank settings;
- додано unit-тести (`tests/test_quiz_bank_client.py`, `tests/test_quiz_bank_schemas.py`,
  `tests/test_quiz_bank_service.py`);
- оновлено `.env.example` новими QUIZ_BANK_* змінними для середовища.

### Критерії для завершення milestone

- повна продакшн-сумісна інтеграція без флоу доставки quiz-питань у цьому milestone.

## Milestone 5 — Training Session Engine

### Поточний статус

`2026-05-14`: core flow implemented (runtime session service, repos, handler flow, keyboards, docs).

### Що виконано в цьому вікні

- додано/оновлено runtime-оркестратор `TrainingSessionService` (`app/services/training_session.py`):
  - bootstrap користувача з `users` repo;
  - створення/закриття сесій (`active`/`completed`/`cancelled`/`failed`);
  - запит питання через `QuizBankService.request_quiz(... )`;
  - кешування pending питання в `api_metadata`;
  - обробка відповіді з перевіркою duplicate та захистом від дублювання score;
  - завершення сесії при досягненні `total_questions`.
- додано/підтримано репозиторії:
  - `app/repositories/users.py`
  - `app/repositories/quiz_sessions.py`
  - `app/repositories/answers.py`
- додано training callbacks/UI:
  - start by theme, next question, finish, resume, new, cancel;
  - безпечний callback (короткий, без повного тексту питання), пояснення після відповіді;
  - дубль відповідей не створює новий answer і не змінює `correct_answers`.
- додано тести:
  - `tests/test_training_session_service.py`
  - `tests/test_training_handlers.py`
  - `tests/test_quiz_keyboards.py`
- оновлено тексти/маршрутизацію/клавіатуру:
  - `app/bot/texts.py`
  - `app/bot/keyboards/quiz.py`
  - `app/bot/handlers/training.py`
  - `app/bot/routers.py`

### Відкриті для наступних milestone

- розгорнута progress aggregation (Milestone 6)
- mistakes lifecycle/review (Milestone 7)
- paywall/subscription/payment logic (Milestone 8/9)

## Milestone 6 — Progress Aggregation

### Поточний статус

`2026-05-14`: completed.

### Що виконано в цьому вікні

- додано `app/repositories/progress.py`:
  - отримання прогресу по `user/level/theme`;
  - create row якщо відсутній;
  - оновлення `total_answered`, `total_correct`, `accuracy`;
  - безпечна робота з негативними значеннями;
  - support summary-читання по користувачу;
  - support summary-читання по `level/theme`.
- додано `app/services/progress.py`:
  - `record_answer_result(...)` для запису відповіді;
  - update `total_answered`;
  - update `total_correct` лише для коректних відповідей;
  - recalculate `accuracy`;
  - update `streak` за наявності поля в моделі;
  - no-op для duplicate-ответів.
- інтегровано progress update в `TrainingSessionService.submit_answer`:
  - виклик тільки для нових валідних відповідей;
  - duplicate-відповідь не змінює прогрес і не змінює score.
- оновлено `app/bot/handlers/profile.py`:
  - відображення реального прогресу з empty-state;
  - fallback до порожнього стану без складної аналітики.
- додано тести:
  - `tests/test_progress_service.py`
  - `tests/test_progress_repository.py`
  - `tests/test_training_progress_integration.py`
  - `tests/test_profile_handlers.py`

### Підтвердження завершення milestone

- `bash scripts/local_ci.sh` — passed
- `make check` — passed
- `python -m pytest -q tests/test_progress_service.py tests/test_progress_repository.py tests/test_training_progress_integration.py tests/test_profile_handlers.py --capture=no` — passed
- `git diff --check` — no whitespace/trailing issues
- Duplicate protection підтверджено:
  - інтеграційний тест `tests/test_training_progress_integration.py` і unit тест `tests/test_progress_service.py`
    перевіряють, що повторна відповідь з `is_duplicate=True` не змінює `total_answered/total_correct`.

## Milestone 7 — Mistakes and Review

### Поточний статус

`2026-05-14`: completed.

### Що виконано в цьому вікні

- додано `app/repositories/mistakes.py`:
  - пошук активної помилки по `user_id + external_quiz_id`;
  - створення/оновлення помилок без дублювання;
  - списування активних помилок користувача;
  - weak areas summary по `level/theme`;
  - закриття помилки після review-success.
- додано `app/services/mistakes.py`:
  - `record_wrong_answer(...)`;
  - `record_review_success(...)`;
  - `get_review_items(...)`;
  - `get_weak_areas(...)`;
  - duplicate-ветка для `is_duplicate=True` не змінює стан.
- інтегровано у training flow (`app/services/training_session.py`):
  - неправильна нова відповідь викликає `record_wrong_answer`;
  - правильна відповідь у review-режимі викликає `record_review_success`;
  - duplicate-відповідь не змінює mistakes.
- додано/оновлено UI для review:
  - `app/bot/handlers/review.py`;
  - `app/bot/keyboards/review.py`;
  - `app/bot/routers.py`;
  - `app/bot/texts.py`.
- додано тести:
  - `tests/test_mistakes_repository.py`
  - `tests/test_mistakes_service.py`
  - `tests/test_training_mistakes_integration.py`
  - `tests/test_review_handlers.py`

### Підтвердження завершення milestone

- `bash scripts/local_ci.sh` — passed
- `make check` — passed
- `python -m pytest -q tests/test_mistakes_repository.py tests/test_mistakes_service.py tests/test_training_mistakes_integration.py tests/test_review_handlers.py --capture=no` — passed
- `git diff --check` — no whitespace/trailing issues
- Duplicate protection підтверджено тестами:
  - `tests/test_mistakes_service.py::test_record_wrong_answer_is_duplicate_does_not_change_state`;
  - `tests/test_training_mistakes_integration.py::test_submit_answer_does_not_repeat_wrong_mistake_on_duplicate_click`.
- Review mode підтверджено тестом `tests/test_review_handlers.py`.

## Milestone 8 — Limits, Entitlements and Subscriptions

### Поточний статус

`2026-05-15`: completed.

### Що виконано в цьому вікні

- оновлено `app/services/entitlements.py`:
  - додано `SubscriptionStatusState` для status screen;
  - active paid access лишається доступним тільки для `active` paid subscription з credited payment;
  - pending, expired, cancelled і failed subscription не відкривають paid access;
  - expiration порівнюється з timezone-normalized UTC datetime;
  - Free/Plus/Pro daily limit hierarchy лишається config-driven через `Settings`.
- оновлено `app/repositories/subscriptions.py`:
  - додано читання останньої subscription для status screen без зміни схеми.
- оновлено subscription UI:
  - `app/bot/handlers/subscription.py`;
  - `app/bot/texts.py`;
  - status screen показує реальний access plan і стан активної, pending або expired paid subscription німецькою.
- уточнено review paywall order:
  - `app/bot/handlers/review.py`;
  - `app/services/training_session_lifecycle.py`;
  - якщо активних помилок немає, показується empty state без paid paywall.
- додано/оновлено тести:
  - `tests/test_entitlements_service.py`;
  - `tests/test_subscription_handlers.py`;
  - `tests/test_review_handlers.py`.

### Підтвердження завершення milestone

- `. .venv/bin/activate && python -m pytest -q tests/test_entitlements_service.py tests/test_subscription_handlers.py tests/test_review_handlers.py tests/test_bot_handlers.py --capture=no` — passed
- `. .venv/bin/activate && python -m pytest -q tests/test_entitlements_service.py tests/test_subscription_handlers.py tests/test_review_handlers.py tests/test_bot_handlers.py tests/test_training_session_service.py tests/test_training_mistakes_integration.py tests/test_training_handlers.py tests/test_profile_handlers.py --capture=no` — passed
- `. .venv/bin/activate && bash scripts/local_ci.sh` — passed
- `git diff --check` — no whitespace/trailing issues
- Міграції не додавались: потрібні таблиці `daily_limits`, `subscriptions` і `payments` уже існують.
- Monthly limits і paywall cooldown не реалізовувались, бо в roadmap вони лишаються Decision Required/config-dependent.

## Milestone 9 — Payments

### Поточний статус

`2026-05-15`: completed.

### Що виконано в цьому вікні

- додано `app/repositories/payments.py`:
  - створення Payment record перед invoice;
  - пошук за idempotency key;
  - пошук за Telegram/provider charge id;
  - lifecycle transitions `created`, `pending`, `paid`, `credited`, `failed`, `cancelled`.
- оновлено `app/repositories/subscriptions.py`:
  - створення active subscription з credited payment;
  - пошук subscription за `payment_id` для idempotency.
- додано `app/services/payments.py`:
  - config-gated Plus/Pro payment plan resolution;
  - Telegram Stars invoice payload;
  - pre-checkout validation;
  - expected user/currency/amount verification;
  - provider reference mismatch rejection;
  - split `confirm_payment(...)` and `credit_payment(...)` so paid status alone does not unlock access;
  - idempotent duplicate provider event handling;
  - payment analytics: `payment_started`, `payment_succeeded`, `payment_failed`, `subscription_started`;
  - audit metadata without provider debug payload dumps or secrets.
- додано Telegram payment handlers:
  - `app/bot/handlers/payments.py`;
  - plan callback starts Stars invoice;
  - pre-checkout answers fail-closed;
  - successful payment confirms and credits subscription.
- оновлено UI/copy/router:
  - `app/bot/keyboards/subscription.py`;
  - `app/bot/texts.py`;
  - `app/bot/routers.py`;
  - `app/bot/handlers/__init__.py`;
  - German success/failure/config-unavailable payment copy.
- оновлено `app/config.py`:
  - optional Stars prices and subscription durations validate as positive values when configured.
- додано/оновлено тести:
  - `tests/test_payments_service.py`;
  - `tests/test_payment_handlers.py`;
  - `tests/test_bot_routers.py`.

### Підтвердження завершення milestone

- `. .venv/bin/activate && python -m pytest -q tests/test_payments_service.py tests/test_payment_handlers.py tests/test_bot_routers.py tests/test_subscription_handlers.py tests/test_bot_handlers.py --capture=no` — passed
- `. .venv/bin/activate && python -m pytest -q tests/test_payments_service.py tests/test_payment_handlers.py tests/test_entitlements_service.py tests/test_subscription_handlers.py tests/test_training_handlers.py tests/test_training_session_service.py tests/test_review_handlers.py tests/test_profile_handlers.py tests/test_bot_routers.py --capture=no` — passed
- `. .venv/bin/activate && bash scripts/local_ci.sh` — passed
- `git diff --check` — no whitespace/trailing issues
- Міграції не додавались: `payments`, `subscriptions` і `analytics_events` уже містять потрібні поля для цього milestone.
- Plus/Pro ціни й duration не hardcoded: invoice creation блокується без runtime config.
- Refund/cancel provider behavior не реалізовувався як Telegram runtime callback, бо фінальна provider-specific поведінка лишається Decision Required/production-integration dependent.
