# Implementation Roadmap Execution Log

## Мета

Виконання цього логу:
- фіксувати статус milestone/рішень з `docs/14_implementation_roadmap.md`;
- робити початок виконання строго в рамках roadmap без розширення scope;
- забезпечити прозорість блокерів перед стартом кодування.

## Поточний стан (2026-05-15)

- Виконання: Milestone 0-9 and M11 closure work completed locally against roadmap gates where credentials are not required.
- Поточний статус: Milestone 0-7 закрито після усунення розривів між roadmap/docs/code/tests:
  Home/onboarding, Quiz Bank availability-driven themes, persisted API error logs,
  Telegram update idempotency, progress rows for available unanswered topics,
  explicit Mistake Screen before review session.
- Додатково 2026-05-15: M0 production decisions re-locked; M8 limits/entitlements,
  M9 payment idempotency and M11 Redis-backed security controls implemented with tests.

## Production Checklist Closure Work

### 2026-06-05

- Payment DB idempotency hardening added for Telegram Stars charge reuse:
  - Alembic head advanced to `202606050001`;
  - `payments.telegram_payment_charge_id` now has unique constraint
    `uq_payments_telegram_payment_charge_id`;
  - runtime schema checks and restore verification checks now require the
    Telegram charge unique constraint in addition to idempotency key and
    provider charge constraints.
- Live/staging Quiz Bank gate coverage strengthened:
  - added `scripts/quiz_bank_live_smoke.py`;
  - `scripts/live_integration_gates.sh` now runs read-only Quiz Bank health,
    levels, themes, title-to-theme-id resolution and availability smoke checks when
    `RUN_QUIZ_BANK_SMOKE=1`;
  - dynamic Quiz Bank question/options/explanation text is checked through
    read-only question lookup when `QUIZ_BANK_SMOKE_ITEM_IDS` is configured,
    without printing the payload.
- Telegram Stars evidence check now fails missing evidence files with an
  explicit sanitized error instead of a traceback.
- Verification passed:
  - focused DB/Alembic model tests;
  - focused payment/security tests;
  - full `scripts/local_ci.sh`;
  - disposable PostgreSQL/Redis runtime smoke on Alembic head `202606050001`;
  - disposable PostgreSQL backup/restore verification with payment idempotency
    integrity checks;
  - Quiz Bank live smoke unit coverage and payment evidence validator tests;
  - secret scan and whitespace diff check.
- Still not closed as production evidence:
  - live Telegram smoke;
  - live/staging Quiz Bank connectivity evidence;
  - Telegram Stars sandbox/live evidence artifact;
  - target monitoring, encrypted target backup/restore and rollback rehearsal.
- No production DB/Redis, production bot polling, payment charge/refund/cancel,
  deploy or secret printing was performed.

## Server Isolated Runtime Evidence

### 2026-06-04

- Polling runtime exception approved by operator for the isolated deploy.
- Deploy path: `/opt/deutsch-trainer-bot/current`.
- Bot: `@Trainer1512_bot`.
- Deployed commit marker:
  `7847a8d478ffb081d682bafbf020adeb2d46a620`.
- Rebuild/restart scope: only `deutsch-trainer-bot-bot-1`.
- DB/Redis remained running and healthy; no DB/Redis restart was performed.
- Migrations already applied; restored Alembic version evidence:
  `202605140002`.
- Quiz Bank protected env was present and runtime connectivity passed without
  printing secrets.
- Manual Telegram flow passed:
  `/start -> menu -> quiz -> question -> answer -> result`.
- `scripts/isolated_runtime_smoke.sh` passed after the stdin regression fix for
  Docker heredoc checks.
- Backup/restore was verified with a temporary dump and disposable restore DB;
  required tables restored and temporary artifacts were removed.
- Rollback target recorded:
  `deutsch-trainer-bot:rollback-ec20844-before-daa7a73-20260604`.
- Payments / Telegram Stars and token rotation were not run.
- Old stacks and adjacent services were not touched.

## Final Closure Gate — M0/M8/M9/M11

### 2026-05-15

- `. .venv/bin/activate && bash scripts/local_ci.sh` — passed.
- Initial `bash scripts/db_runtime_check.sh` without `DATABASE_URL` stopped as expected with
  `DATABASE_URL or TEST_DATABASE_URL is required for runtime verification`.
- PostgreSQL runtime check was then run against Docker PostgreSQL on `localhost:5433`:
  - `DATABASE_URL='postgresql+asyncpg://postgres:postgres@localhost:5433/deutsch_trainer' alembic upgrade head` — passed.
  - `DATABASE_URL='postgresql+asyncpg://postgres:postgres@localhost:5433/deutsch_trainer' bash scripts/db_runtime_check.sh` — passed.
  - Runtime schema verification finished with Alembic current `202605140002 (head)` and `alembic check` reporting `No new upgrade operations detected`.
- Focused payment/security regression:
  - `python -m pytest -q tests/test_security_controls.py tests/test_entitlements_service.py tests/test_payments_service.py tests/test_payment_handlers.py tests/test_admin_handlers.py tests/test_analytics_service.py tests/test_foundation.py --capture=no` — passed.
- `git diff --check` — passed.

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

### Release 1 launch configuration

- Free daily limit: `5`.
- Plus daily limit: `25`.
- Pro daily limit: `100`.
- Plus package: `100` Telegram Stars / `30` days.
- Pro package: `250` Telegram Stars / `90` days.
- Telegram Stars mode: `test` by default, `prod` required by production secret validation.
- Monthly limits: Decision closed as `not in Release 1`.
- Paywall cooldown: Decision closed as `none`.

### Gate

- Milestone 1 can start.  
- Milestone 2 can start after DB schema planning and migration design.

## Milestone 8 — Limits, Entitlements and Subscriptions

### Поточний статус

`2026-05-15`: completed for Release 1 code scope.

### Що виконано

- Daily limits are config-driven with locked defaults:
  `FREE_DAILY_QUESTION_LIMIT=5`, `PLUS_DAILY_QUESTION_LIMIT=25`,
  `PRO_DAILY_QUESTION_LIMIT=100`.
- Config validation enforces `Free < Plus < Pro`.
- Monthly limits are explicitly not in Release 1.
- Paywall cooldown policy is explicitly `none`.
- Service-layer entitlements require Plus/Pro for paid features independently from UI.
- Active paid access requires an active non-expired subscription joined to a credited payment.
- Pending/uncredited subscriptions do not unlock paid access.
- Expiration returns the user to Free access without deleting progress, mistakes, payments or subscription history.

### Evidence

- `tests/test_entitlements_service.py`
- `tests/test_security_controls.py`
- Focused run: `python -m pytest -q tests/test_security_controls.py tests/test_entitlements_service.py tests/test_payments_service.py tests/test_payment_handlers.py --capture=no` — passed.

## Milestone 9 — Payments

### Поточний статус

`2026-05-15`: completed for local Telegram Stars service/handler flow.

### Що виконано

- Approved packages:
  - Plus: `100` Stars, `30` days.
  - Pro: `250` Stars, `90` days.
- Telegram Stars payload format locked: `dtbpay:{payment_id}:{idempotency_key}`.
- Provider fields locked: currency `XTR`, empty provider token for Stars, charge references validated when present.
- Local payment flow covers invoice creation, pre-checkout validation, successful payment confirmation, credit and active subscription.
- QA mismatch coverage includes wrong user, wrong amount, unsupported/wrong plan, duplicate provider event, duplicate payload with different reference and reused provider reference.
- Paid access remains locked until `payment.status=credited` and an active subscription exists.
- Cancel/refund automation is explicitly unsupported in Release 1 bot runtime; manual provider/operator handling remains outside code scope.

### Evidence

- `app/services/payments.py`
- `app/bot/handlers/payments.py`
- `tests/test_payments_service.py`
- `tests/test_payment_handlers.py`
- Focused run: `python -m pytest -q tests/test_security_controls.py tests/test_entitlements_service.py tests/test_payments_service.py tests/test_payment_handlers.py --capture=no` — passed.

### Недоведено до production release

- Real Telegram Stars test-mode execution with live Telegram credentials was not run in this local repository pass.

## Milestone 11 — Security and Abuse Protection

### Поточний статус

`2026-05-15`: completed for code-level security controls; production deployment evidence remains M12.

### Що виконано

- Redis-backed global sliding-window rate limiter added for multi-process staging/production.
- Redis-backed duplicate Telegram update guard added for webhook/runtime state.
- Development keeps in-memory backend by default; staging/production `auto` resolves to Redis.
- `SECURITY_STATE_BACKEND=in_memory` is rejected outside development.
- Production startup requires webhook mode, webhook secret, DB URL, Redis URL and `TELEGRAM_STARS_MODE=prod`.
- Admin metrics are owner-only through `ADMIN_TELEGRAM_USER_IDS`.
- Logs and analytics reject/redact tokens, secrets, DB URLs, provider payloads and raw sensitive metadata.
- Backup encryption/restricted access is locked as a security control in `docs/16_architecture_lock.md` and `docs/13_operations.md`.

### Evidence

- `app/security/rate_limits.py`
- `app/bot/middlewares/security.py`
- `app/bot/dispatcher.py`
- `app/logging_config.py`
- `app/repositories/analytics_events.py`
- `tests/test_security_controls.py`
- `tests/test_admin_handlers.py`
- `tests/test_analytics_service.py`
- Focused run: `python -m pytest -q tests/test_security_controls.py tests/test_entitlements_service.py tests/test_payments_service.py tests/test_payment_handlers.py --capture=no` — passed.

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
      `uq_payments_telegram_payment_charge_id`, `uq_payments_provider_payment_charge_id`
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

- Real Telegram Stars test/prod run requires safe credentials and cannot be proven by local tests alone.
- Production domain value and webhook registration evidence live in deploy inventory, not committed docs.
- Нестабільне покриття та regressions у German copy залишаються QA-ризиками.
- Готовність backup/restore/rollback валідатиметься на Milestone 12.

## Вимоги до виконання (далі)

1. Run full local CI before final close-out.
2. Run PostgreSQL runtime verification when `DATABASE_URL` or `TEST_DATABASE_URL` is available.
3. Keep production release blocked until M12 backup/restore/monitoring/deploy evidence exists.

## Milestone 12 — Operations and Deployment

### Поточний статус

`2026-05-17`: repo-side operations/deployment artifacts completed, with
local disposable PostgreSQL backup/restore verification.

Production release remains blocked without target-environment evidence.

### Що виконано

- Added standalone production Compose artifact:
  - `docker-compose.production.yml`.
- Added deployment templates without committed real domain or secrets:
  - `deploy/Caddyfile.production.template`;
  - `deploy/env.production.template`;
  - `deploy/env.staging.template`.
- Added non-mutating operations scripts:
  - `scripts/ops_preflight.sh`;
  - `scripts/ops_smoke.sh`.
- Added PostgreSQL backup/restore artifacts:
  - `scripts/postgres_backup.sh`;
  - `scripts/postgres_restore_verify.sh`.
- Added concrete runbook:
  - `docs/20_operations_deployment_runbook.md`.
- Updated `docs/13_operations.md` with M12 artifact index, backup/restore artifacts
  and explicit evidence gate.

### Підтвердження в репозиторії

- `. .venv/bin/activate && bash scripts/local_ci.sh` — passed.
- `bash -n scripts/ops_preflight.sh scripts/ops_smoke.sh scripts/postgres_backup.sh scripts/postgres_restore_verify.sh` — passed.
- Shell safety invariant verified: all added shell scripts contain `set -euo pipefail`.
- Secret-output invariant checked with `rg`: no `set -x` or direct printing of secret env values in added shell scripts.
- `docker compose -f docker-compose.production.yml config --quiet` with local dummy placeholder values — passed.
- `bash scripts/* --help` for added M12 scripts — passed.
- `git diff --check` — passed.
- Added-file trailing whitespace scan with `rg` — no findings.
- Disposable local PostgreSQL backup/restore verification — passed:
  - started two temporary Docker PostgreSQL containers on a private Docker network;
  - ran `alembic upgrade head` against the source DB;
  - ran `scripts/postgres_backup.sh` inside a temporary official PostgreSQL
    client container with `BACKUP_ENCRYPTION=none` and `APP_ENV=development`;
  - ran `scripts/postgres_restore_verify.sh` against the restore DB;
  - restore script verified checksum, schema presence, payment idempotency
    constraints, duplicate subscription/payment guards, active mistake
    uniqueness and progress counter integrity;
  - temporary containers, network and backup files were removed.
- `DATABASE_URL` / `TEST_DATABASE_URL` availability check — unavailable in this
  session; `bash scripts/db_runtime_check.sh` was not run.

### Недоведено без staging/production доступу

- Real production domain and HTTPS endpoint.
- Telegram webhook registration evidence.
- Protected runtime credential injection.
- Monitoring evidence for bot, Caddy, DB, Redis, Quiz Bank, payments,
  subscriptions, admin auth failures, logs and backups.
- Encrypted backup created in target environment.
- Restore verification against a disposable target-environment database.
- Staging smoke test with safe credentials.
- Production post-deploy smoke test.
- Rollback execution evidence.

### Release gate

Production deploy remains blocked until the external evidence above exists and
Milestone 13 QA gates are closed or explicitly accepted by the responsible
owner.

## Milestone 13 — QA and Test Strategy

### Поточний статус

`2026-05-26`: completed for repository-side QA gates and local evidence.

Production release remains blocked until target-environment QA evidence exists
or external failures are explicitly accepted by the responsible owner.

### Що виконано

- Added modular release QA gate runner:
  - `scripts/qa_release_gates.py`;
  - stable critical gates for Python integrity, static policy, secret scan,
    progress logic, answer→analytics flow, Telegram flows, Quiz Bank
    contract/failure tests, payment/subscription tests, security/abuse tests,
    German copy, gate-runner contract and full regression.
  - partial gate runs produce `result=blocked` and `release_blocked=true`
    until all critical gates are executed.
  - failed critical gates remain blocking unless explicit owner acceptance
    records `accepted_by`, `reason` and `accepted_at`.
  - stdout/stderr tails stored in evidence are redacted for secret-like values.
- Wired GitHub CI to run the full Milestone 13 QA release runner and upload
  `qa_evidence/ci_release_gates.json` as a workflow artifact.
- Added QA runner contract tests:
  - `tests/test_qa_release_gates.py`.
- Added German-only user-facing copy checks:
  - `tests/test_german_copy.py`.
- Split the old training session service test monolith into behavior-focused
  modules:
  - `tests/fakes/training_session.py`;
  - `tests/test_training_session_lifecycle.py`;
  - `tests/test_training_session_answer_flow.py`;
  - `tests/test_training_session_api_limits.py`;
  - `tests/test_training_session_service.py` remains as a small compatibility
    placeholder for the previously tracked path.
- Wired local CI to validate the QA gate plan before regular checks:
  - `scripts/local_ci.sh`.
- Updated QA documentation with concrete gate IDs, command usage and evidence
  standard:
  - `docs/12_quality_assurance.md`.
- Added `qa_evidence/` to `.gitignore` so local evidence can be generated
  without committing runtime reports.

### Підтвердження в репозиторії

- `. .venv/bin/activate && python -m pytest -q --capture=no tests/test_training_session_lifecycle.py tests/test_training_session_answer_flow.py tests/test_training_session_api_limits.py tests/test_german_copy.py tests/test_qa_release_gates.py` — passed.
- `. .venv/bin/activate && python scripts/qa_release_gates.py --environment local --evidence-file qa_evidence/milestone13_local.json` — passed, 12/12 gates.
- Local QA evidence summary:
  - `result`: `passed`;
  - `release_blocked`: `false`;
  - `gate_coverage`: `full`;
  - `environment`: `local`;
  - `gate_results`: `12`;
  - `failed_cases`: `[]`;
  - `missing_gate_ids`: `[]`;
  - `tested_at`: `2026-05-26T18:55:55.289013+00:00`;
  - `build_or_commit`: `7079af5+dirty`.
- `. .venv/bin/activate && python scripts/qa_release_gates.py --gate german-copy --environment local --evidence-file qa_evidence/partial_debug.json; test $? -eq 1` — passed; partial gate evidence is blocked as expected.
- `. .venv/bin/activate && bash scripts/local_ci.sh` — passed.

### Недоведено без staging/production доступу

- Live Telegram Stars test/prod payment execution.
- Staging webhook registration and Telegram update delivery.
- Production Quiz Bank availability under real protected credentials.
- Production deployment smoke test and monitoring evidence.

## Production Readiness Evidence Plan — After Milestone 13

### 2026-05-26 full repo/local evidence pass

- Scope: repository-side and local disposable environment evidence before any
  external production-readiness work.
- Environment: local virtual environment, local Docker, disposable PostgreSQL
  and Redis containers, dummy placeholder environment values only.
- Command/action:
  - `. .venv/bin/activate && python scripts/qa_release_gates.py --environment local --evidence-file qa_evidence/production_readiness_local.json`;
  - disposable PostgreSQL `alembic upgrade head` and `bash scripts/db_runtime_check.sh`;
  - staging-like `bash scripts/ops_preflight.sh` with disposable PostgreSQL,
    disposable Redis and dummy placeholder values; `RUN_EXTERNAL_PREFLIGHT`
    was not enabled;
  - `bash -n scripts/ops_preflight.sh scripts/ops_smoke.sh scripts/postgres_backup.sh scripts/postgres_restore_verify.sh`;
  - `bash scripts/ops_preflight.sh --help && bash scripts/ops_smoke.sh --help && bash scripts/postgres_backup.sh --help && bash scripts/postgres_restore_verify.sh --help`;
  - `docker compose -f docker-compose.production.yml config --quiet` with
    dummy placeholder environment values;
  - disposable local PostgreSQL backup/restore using `scripts/postgres_backup.sh`
    with `APP_ENV=development` and `BACKUP_ENCRYPTION=none`, then
    `scripts/postgres_restore_verify.sh` against a separate disposable restore
    DB;
  - `. .venv/bin/activate && bash scripts/local_ci.sh`;
  - `git diff --check`.
- Result: passed for repo/local scope. QA runner passed 12/12 gates with
  `result=passed`, `release_blocked=false`, `gate_coverage=full`,
  `environment=local`, `failed_cases=[]`, `missing_gate_ids=[]`,
  `tested_at=2026-05-26T19:32:45.073911+00:00`, `build_or_commit=550af16+dirty`.
  Runtime DB verification reached Alembic `202605140002 (head)`. Backup/restore
  verified checksum, restored schema and integrity checks.
- Timestamp: `2026-05-26T19:34:37Z`.
- Failures: an initial pre-consolidation `local_ci` run failed on the synthetic
  redaction fixture in `tests/test_qa_release_gates.py`; the fixture was split
  into non-secret-shaped fragments, then secret scan and final local CI passed.
- Known risks: this proves repo/local readiness only. It does not prove staging
  or production target inventory, protected secret injection, Telegram webhook
  delivery, live Telegram Stars payments, live Quiz Bank monitoring, active
  target monitoring, encrypted target backup, target restore, rollback behavior
  or production smoke.
- Owner acceptance: none recorded.

### 2026-05-26 external gate records

These records are not production closure evidence. They define the required
staging-first actions and record why each gate remains open in this local pass.

| Gate | Scope | Environment | Command/action | Result | Timestamp | Failures | Known risks | Owner acceptance |
|---|---|---|---|---|---|---|---|---|
| Telegram E2E smoke | `/start` through onboarding, level, theme, training, result, progress and mistake review. | Staging first; production only after explicit approval. | Manual Telegram smoke with safe staging bot credentials, staging DB, staging Redis and approved Quiz Bank smoke data; capture non-secret transcript/result. | Blocked, not run: no staging target inventory, bot token, webhook/domain evidence or protected credentials were available. | `2026-05-26T19:34:37Z` | Not applicable; command/action was not executed. | Local handler tests cannot prove Telegram delivery, webhook routing, real callback payloads or target DB writes. | None recorded. |
| Quiz Bank monitoring evidence | Runtime Quiz Bank health, latency/error monitoring and protected credential path. | Staging first; production evidence before release. | `SMOKE_BASE_URL=https://<staging-domain-managed-outside-repo> RUN_QUIZ_BANK_SMOKE=1 bash scripts/ops_smoke.sh`, plus monitoring dashboard/alert evidence for Quiz Bank API. | Blocked, not run: no target Quiz Bank credentials, endpoint inventory or monitoring access was available. | `2026-05-26T19:34:37Z` | Not applicable; command/action was not executed. | Contract tests do not prove live availability, alert routing or production credential wiring. | None recorded. |
| Telegram Stars payment evidence | Live test/prod payment path, invoice, pre-checkout, successful payment, idempotent credit and subscription activation. | Telegram Stars test mode first; production mode only with explicit approval. | Execute approved Stars test payment in staging with `TELEGRAM_STARS_MODE=test`; production payment evidence requires separate approval and owner sign-off. | Blocked, not run: no live Telegram payment credentials/test approval or production approval was available. | `2026-05-26T19:34:37Z` | Not applicable; command/action was not executed. | Local payment tests cannot prove Telegram provider behavior, live pre-checkout delivery or production Stars configuration. | None recorded. |

Monetization production readiness remains blocked until Telegram Stars sandbox
or approved live evidence proves real invoice payload delivery, pre-checkout
delivery, `telegram_payment_charge_id` presence, successful payment delivery and
active subscription crediting. Green local tests are not sufficient for this
gate.
| Active monitoring | Bot, DB, Redis, Quiz Bank API, payments, subscriptions, logs and backups. | Staging first; production before release. | Verify target dashboards/alerts and run non-mutating health checks from `docs/20_operations_deployment_runbook.md`. | Blocked, not run: no monitoring system access or target environment inventory was available. | `2026-05-26T19:34:37Z` | Not applicable; command/action was not executed. | Monitoring artifacts in repo do not prove active alerting, retention, routing or operator visibility. | None recorded. |
| Production backup configured | Encrypted, access-controlled PostgreSQL backup in target storage. | Production, after explicit approval. | `APP_ENV=production BACKUP_ENCRYPTION=age bash scripts/postgres_backup.sh` from protected target environment; verify restricted backup path/access without printing secrets. | Blocked, not run: production DB, backup storage, encryption recipient/key and production approval were not available. | `2026-05-26T19:34:37Z` | Not applicable; command/action was not executed. | Local backup script evidence does not prove target encryption, retention, operator access control or storage durability. | None recorded. |
| Target-environment backup/restore verification | Restore latest target backup into disposable non-production DB and verify schema/idempotency checks. | Staging or disposable target restore DB; never production restore target. | `RESTORE_CONFIRM_NON_PRODUCTION=I_UNDERSTAND_THIS_IS_NOT_PRODUCTION bash scripts/postgres_restore_verify.sh` using target backup and disposable restore DB. | Blocked, not run: no target backup artifact, restore DB or backup access credentials were available. | `2026-05-26T19:34:37Z` | Not applicable; command/action was not executed. | Local disposable restore evidence does not prove target backup decryptability, restore access or target-data integrity. | None recorded. |
| Rollback readiness | Previous known-good image/Compose target, migration impact review and post-rollback smoke. | Staging first; production only where feasible and approved. | Execute staging rollback rehearsal from `docs/20_operations_deployment_runbook.md`, then run post-rollback smoke and integrity checks. | Blocked, not run: no staging deploy target, immutable image inventory or rollback target was available. | `2026-05-26T19:34:37Z` | Not applicable; command/action was not executed. | Runbook alone does not prove rollback timing, migration safety, payment idempotency or recovery monitoring. | None recorded. |
| Production smoke tests | HTTPS health, Telegram getMe/webhook delivery, Quiz Bank smoke, Telegram user journey, payments/admin/log/monitoring checks. | Production only after explicit deploy and smoke approval. | `SMOKE_BASE_URL=https://<production-domain-managed-outside-repo> RUN_TELEGRAM_SMOKE=1 RUN_QUIZ_BANK_SMOKE=1 bash scripts/ops_smoke.sh`, plus approved manual Telegram and monitoring checks. | Blocked, not run: no production deploy approval, domain, webhook registration evidence, protected credentials or monitoring access was available. | `2026-05-26T19:34:37Z` | Not applicable; command/action was not executed. | Production release remains blocked until smoke passes in the real target environment without exposing secrets. | None recorded. |

### 2026-06-04 isolated server deploy evidence

This record captures the isolated server deployment proof for
`/opt/deutsch-trainer-bot`. It is operational evidence for the active isolated
runtime, not a full production-release closure.

| Gate | Scope | Environment | Command/action | Result | Timestamp | Failures | Known risks | Owner acceptance |
|---|---|---|---|---|---|---|---|---|
| Isolated deploy runtime | Bot, isolated PostgreSQL and isolated Redis run under the `deutsch-trainer-bot` Compose project without touching legacy stacks. | Isolated server runtime. | Inspect isolated Compose project and running containers; verify bot process, DB and Redis are running. | Passed: `deutsch-trainer-bot-bot-1`, `deutsch-trainer-bot-db-1` and `deutsch-trainer-bot-redis-1` were running; legacy stacks were not restarted or modified. | `2026-06-04` | None recorded. | This proves the isolated server runtime only; it does not create GitHub release provenance or close webhook-vs-polling production mode. | User accepted server isolated deploy as `Done`. |
| Isolated DB schema | Alembic migrations applied to the isolated PostgreSQL database. | Isolated server runtime. | Run the isolated `migrate` service with `--no-deps`; inspect required tables and Alembic head without printing credentials. | Passed: `users`, `quiz_sessions`, `user_answers`, `progress`, `mistakes` and `alembic_version` were present at Alembic revision `202605140002`. | `2026-06-04` | Initial runtime logs showed `relation "users" does not exist`; applying migrations resolved this for the isolated DB. | This does not prove restore from encrypted target backup. | User accepted DB migration stage. |
| Quiz Bank runtime env | Protected Quiz Bank credentials wired into the isolated bot runtime without printing secret values. | Isolated server runtime. | Copy existing protected env values into `/opt/deutsch-trainer-bot/shared/runtime.env`; verify required variable presence inside the bot container. | Passed: `QUIZ_BANK_API_BASE_URL`, `QUIZ_BANK_EDGE_API_KEY`, `QUIZ_BANK_CONSUMER_ID` and `QUIZ_BANK_CONSUMER_API_KEY` were present. | `2026-06-04` | None recorded. | Secret values were not printed; token rotation remains a separate post-stabilization task. | User accepted Quiz Bank connection scope. |
| Quiz Bank client contract | Bot client uses the live Quiz Bank v1 contract. | Local repo plus isolated server runtime. | Patch bot client for `/v1/levels`, `/v1/topics`, `/v1/quiz-items/next` and `/v1/quiz-items/{item_id}`; run local CI and service-level smoke. | Passed: local CI passed; runtime service-level smoke fetched levels, themes and one question with answer feedback. | `2026-06-04` | The live API returned `CONSUMER_THEME_NOT_ALLOWED` for at least one themed request; the client retries without `theme_ids`. | Selected theme may be relaxed to an unthemed request when consumer scope rejects the theme. | User accepted basic runtime proof; theme-scope policy remains a follow-up risk. |
| Manual Telegram journey | `/start`, main menu, quiz start, question delivery, answer and result. | Live Telegram bot `@Trainer1512_bot` against isolated server runtime. | Operator manually used Telegram and confirmed the full journey. Agent verified earlier server-side update handling, DB user evidence and clean logs where observable. | Passed: user confirmed `/start -> menu -> quiz -> question -> answer -> result`. | `2026-06-04` | Callback payloads were not visible in the original runtime logs. | Safe callback-route logging was added locally after this proof; it still needs a future deploy before it improves server logs. | User explicitly confirmed the manual Telegram flow. |
| Payment and token rotation hold | Keep Telegram Stars and token rotation out of this runtime proof. | Isolated server runtime and local repo. | Do not run payment flows; do not rotate tokens while the bot is stabilizing. | Passed: no payment or Telegram Stars flow was run; token rotation was not performed. | `2026-06-04` | None recorded. | Telegram Stars production proof and token rotation remain separate controlled tasks. | User instructed not to run payment and to defer token rotation. |

### 2026-06-04 local readiness continuation

- Added safe callback-route logging locally so future runtime logs can show
  callback families without raw callback payloads, answer tokens or secrets.
- Added `scripts/isolated_runtime_smoke.sh` for non-mutating isolated polling
  runtime checks.
- Added `scripts/git_release_preflight.sh` to block release provenance work when
  the feature branch, clean worktree or correct remote are not verified.
- Added shell artifact validation to `scripts/static_policy_check.py`.
- Added a regression test proving progress uses the Quiz Bank returned question
  theme when the requested theme and returned theme differ.
- Updated operations docs with a polling runtime exception gate, secret rotation
  procedure and git release provenance gate.
- Verification:
  - `. .venv/bin/activate && bash scripts/local_ci.sh` — passed.
  - `. .venv/bin/activate && python scripts/qa_release_gates.py --environment local --known-risk "Local QA gates do not prove live Telegram Stars, target monitoring, target backup/restore, GitHub release provenance, or production deployment evidence."` — passed 12/12 gates with `release_blocked=false` for local evidence.
- Known risks: this remains local/repo evidence. It does not prove target
  monitoring, target backup/restore, production rollback, Telegram Stars live
  behavior, GitHub remote publication or a final webhook-vs-approved-polling
  production runtime decision.

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
- Monthly limits не реалізовувались, бо рішення закрите як `not in Release 1`.
- Paywall cooldown не реалізовувався, бо Release 1 policy is `PAYWALL_COOLDOWN_POLICY=none`.

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
  - approved Stars prices and subscription durations мають validated defaults;
  - production requires `TELEGRAM_STARS_MODE=prod`;
  - invalid/missing explicit overrides fail closed.
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
- Plus/Pro ціни й duration locked as typed launch config defaults and can be overridden only through validated env.
- Refund/cancel provider behavior не реалізовувався як Telegram runtime callback, бо Release 1 decision is unsupported/manual provider/operator handling.

## Milestone 10 — Analytics and Admin Metrics

### Поточний статус

`2026-05-15`: completed.

### Що виконано в цьому вікні

- додано `app/services/analytics.py`:
  - best-effort `AnalyticsTracker`, який не ламає user flow при падінні analytics write;
  - daily admin metrics для users, active users, sessions, answers, subscriptions, payments, API errors і learning health;
  - retention D1/D7/D30;
  - paywall CTR, payment success, Free→Plus, Plus→Pro і expiration recovery metrics;
  - German admin report formatter.
- оновлено `app/repositories/analytics_events.py`:
  - append-only event writes лишилися append-only;
  - unsafe metadata keys відхиляються через `analytics_event_rejected` без збереження raw payload/secrets;
  - додано read helper для недубльованого `subscription_expired`.
- підключено Milestone 10 events:
  - onboarding: `bot_started`, `user_created`, `level_selected`, `theme_selected`;
  - learning: `training_started`, `question_answered`, `training_completed`, `result_shown`, `progress_opened`, `mistakes_opened`, `mistakes_repeated`, `recommendation_shown`;
  - monetization: `paywall_shown`, `paywall_clicked`, `subscription_opened`, `payment_started`, `payment_succeeded`, `payment_failed`, `subscription_started`, `subscription_expired`;
  - operations: `quiz_api_request_failed`, `quiz_api_invalid_response`.
- додано owner-only admin command:
  - `app/bot/handlers/admin.py`;
  - `ADMIN_TELEGRAM_USER_IDS` у `app/config.py`;
  - router підключено в `app/bot/routers.py`;
  - unauthorized users receive generic German denial copy.
- оновлено payment analytics:
  - `paywall_clicked` пишеться перед `payment_started`;
  - `subscription_started` лишається прив'язаним до credited subscription state, не до raw provider callback.
- додано/оновлено тести:
  - `tests/test_analytics_service.py`;
  - `tests/test_admin_handlers.py`;
  - `tests/test_bot_routers.py`;
  - `tests/test_payments_service.py`.

### Підтвердження завершення milestone

- `. .venv/bin/activate && python -m pytest -q tests/test_analytics_service.py tests/test_admin_handlers.py tests/test_bot_routers.py tests/test_payments_service.py tests/test_payment_handlers.py tests/test_entitlements_service.py tests/test_subscription_handlers.py tests/test_training_handlers.py tests/test_profile_handlers.py tests/test_review_handlers.py --capture=no` — passed
- `. .venv/bin/activate && python -m compileall app tests` — passed
- `. .venv/bin/activate && bash scripts/local_ci.sh` — passed
- `. .venv/bin/activate && python scripts/secret_scan.py` — passed
- `git diff --check` — no whitespace/trailing issues
- Міграції не додавались: потрібні таблиці `analytics_events`, `api_error_logs`, `users`, `quiz_sessions`, `user_answers`, `subscriptions` і `payments` уже існують.

## Milestone 11 — Security and Abuse Protection

### Поточний статус

`2026-05-15`: completed.

### Що виконано в цьому вікні

- додано security controls:
  - `app/security/rate_limits.py`;
  - sliding-window rate limits для `/start`, training start, answer callbacks, retry/next, paywall click, payment start і admin;
  - in-memory limiter/duplicate guard for development and tests;
  - Redis-backed limiter/duplicate guard for staging/production multi-process runtime.
- додано Telegram security middleware:
  - `app/bot/middlewares/security.py`;
  - middleware підключено в `app/bot/dispatcher.py`;
  - duplicate updates drop without handler execution;
  - rate-limit hits return safe German copy without raw payload logging.
- оновлено webhook/config security:
  - webhook mode outside development requires HTTPS URL and webhook secret;
- duplicate update TTL, rate-limit switch and security state backend are environment-driven settings.
- `SECURITY_STATE_BACKEND=in_memory` is rejected outside development.
- посилено secret/privacy controls:
  - log redaction covers authorization, bearer values, credentials, database URLs, Telegram token shape and private-key blocks;
  - analytics metadata rejects unsafe secret-like keys and values through `analytics_event_rejected`.
- підтверджено existing ownership/idempotency controls додатковими regression tests:
  - payment pre-checkout rejects invoice owned by another Telegram user;
  - duplicate update middleware prevents repeated handler execution;
  - duplicate provider payment event behavior лишається idempotent from Milestone 9 tests.

### Підтвердження завершення milestone

- `. .venv/bin/activate && python -m pytest -q tests/test_security_controls.py tests/test_bot_routers.py tests/test_foundation.py tests/test_analytics_service.py tests/test_payments_service.py --capture=no` — passed
- `. .venv/bin/activate && python scripts/secret_scan.py` — passed
- `. .venv/bin/activate && bash scripts/local_ci.sh` — passed
- `git diff --check` — passed in final closure gate
- Міграції не додавались: Milestone 11 реалізовано через middleware/config/service-level controls і tests без зміни schema.
- Redis-backed global rate limiting and duplicate update guard are implemented for non-development runtime.
