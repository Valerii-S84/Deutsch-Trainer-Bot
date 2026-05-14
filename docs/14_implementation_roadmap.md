# 14. Implementation Roadmap

## 1. Purpose

Цей roadmap описує шлях реалізації Deutsch Trainer Bot до повного production-ready стану.

Документ не описує експеримент, прототип або урізану версію. Він фіксує порядок робіт для повноцінного Telegram quiz bot, який працює з Quiz Bank API, зберігає навчальний стан користувача, підтримує прогрес, помилки, ліміти, підписки, Telegram Stars payments, аналітику, адмінські метрики, безпеку, QA, backup, restore, deployment і rollback.

Roadmap має виконуватися без послаблення продуктових інваріантів:

- user-facing Telegram UI тільки німецькою мовою;
- Quiz Bank API є canonical source of learning content;
- бот зберігає learning state, а не локальний банк питань;
- кожна accepted відповідь оновлює progress або коректно відхиляється як duplicate;
- API failure не створює fake progress і не списує daily limit;
- payment credit є idempotent;
- subscription expiration не видаляє навчальні дані;
- production не готовий без QA gates, monitoring, backup/restore і rollback plan.

## 2. Production Target

Кінцевий production стан системи:

- стабільний Telegram bot runtime, який обробляє `/start`, callback-и, training sessions, payment events і safe fallback states;
- інтеграція з Quiz Bank API через validated HTTP client, auth headers, timeout, retry, cache policy, circuit breaker і contract tests;
- persistent relational storage для users, sessions, answers, progress, mistakes, subscriptions, payments, analytics, audit і API errors;
- PostgreSQL як затверджена фінальна persistent database;
- підтримка Free, Plus і Pro access rules через entitlements, daily/monthly limits і subscription status;
- Telegram Stars payment flow з invoice creation, payment verification, idempotent credit, failed/cancelled states і payment audit log;
- user progress по level + theme: accuracy, coverage, stability, weakness, recency, topic status, level progress і learning history;
- mistakes tracking з mistake lifecycle, mistake history, review mode і resolution тільки після повторних правильних відповідей у різні дні;
- analytics events для activation, learning value, retention, paywall, payment, subscription і API diagnostics;
- protected admin metrics для users, activity, sessions, answers, subscriptions, payments, API errors, payment errors і learning metrics;
- monitoring для bot health, Telegram handling, database, Quiz Bank API, payments, subscriptions, backups і security signals;
- encrypted backup, protected backup access і tested restore без duplicate payment credit;
- security controls для secrets, webhook, API keys, admin access, user ownership, rate limits, logs і analytics redaction;
- QA strategy з unit, integration, contract, Telegram flow, payment, subscription, progress, security і regression gates;
- repeatable Docker-based deployment, environment separation, webhook setup, smoke tests, rollback plan і incident response.

## 3. Architecture Decisions and Remaining Required Decisions

Current Architecture Lock status is maintained in `docs/16_architecture_lock.md`.
Rows marked as locked below are no longer open coding blockers; changing them
requires a new explicit architecture decision.

| Area | Decision Needed | Options | Recommended Direction | Owner | Blocking? |
|---|---|---|---|---|---|
| Implementation stack | Locked: Python 3.12+ | Python, Node.js/TypeScript, інший backend stack | Closed in `docs/16_architecture_lock.md`; Python 3.12+ is active | Tech owner | No |
| Telegram bot framework | Locked: aiogram 3.x | aiogram, python-telegram-bot, Telegraf, grammY, інший | Closed in `docs/16_architecture_lock.md`; aiogram 3.x is active | Tech owner | No |
| Database choice | Locked: PostgreSQL | PostgreSQL, managed relational DB, інша транзакційна БД | Closed in `docs/16_architecture_lock.md`; PostgreSQL is primary | Tech owner | No |
| ORM / migrations | Locked: SQLAlchemy 2.x async + Alembic | SQLAlchemy/Alembic, Prisma, Drizzle, raw SQL migrations, інше | Closed in `docs/16_architecture_lock.md`; models and migrations must stay aligned | Tech owner | No |
| Hosting/deployment target | Locked direction: Hetzner VPS + Docker Compose + Caddy | VPS, managed container platform, PaaS, cloud service | Closed in `docs/16_architecture_lock.md`; exact production runbook remains operations work | Tech owner / Ops owner | No for coding; Yes before deploy |
| Telegram update mode | Locked: local polling, production HTTPS webhook | Webhook, long polling | Closed in `docs/16_architecture_lock.md`; production polling requires explicit approval | Tech owner / Ops owner | No for coding; Yes before deploy |
| Production domain / webhook setup | Production domain, HTTPS certificate, webhook path and webhook secret | Own domain, provider domain, reverse proxy | Decision Required before production deploy; must preserve HTTPS and webhook secret verification | Ops owner | Yes before deploy |
| Repo structure | Active layout: `app/`, `tests/`, `alembic/`, `docs/`, `scripts/` | `src/`, `tests/`, `infra/`, `docs/`; stack-specific layout | Closed for current implementation; future layout changes require explicit scope | Tech owner | No |
| Config strategy | Locked: environment variables plus typed validation | Environment variables, typed config files with env injection, secret manager | Closed in current implementation; no secrets in repo | Tech owner / Ops owner | No |
| Secrets strategy | Locked: runtime env/secrets only | Provider secret store, encrypted env, VPS secret injection | Closed as policy; exact production secret store remains deploy/runbook work | Ops owner | No for coding; Yes before deploy |
| Quiz Bank API contract | Final OpenAPI/HTTP contract, auth, fields, errors | Existing API spec, generated OpenAPI, agreed manual contract | Decision Required; contract must include levels, themes, availability, questions, lookup, metadata and error taxonomy | Product owner / API owner / Tech owner | Yes |
| Quiz Bank cache policy | TTL and allowed cache scope | Catalog cache, availability cache, session buffer | Use only allowed caches; never full local question bank; exact TTL Decision Required | Tech owner / Ops owner | Yes |
| Payment details | Telegram Stars provider flow and verification details | Telegram Stars only for Release 1, additional provider only if approved | Telegram Stars per product docs; exact payload, invoice, provider references and verification must be locked | Product owner / Tech owner | Yes |
| Plus/Pro durations | Subscription period per plan | 7 days, 30 days, monthly, custom | Decision Required; do not hardcode until launch configuration is approved | Product owner | Yes |
| Prices | Plus and Pro prices in Telegram Stars | Product-defined Stars amounts | Decision Required; no default prices in code or docs | Product owner | Yes |
| Telegram Stars config | Currency/unit, invoice payload, provider fields, test/prod mode | Telegram Stars settings | Decision Required; must separate test and production credentials/config | Product owner / Tech owner | Yes |
| Plan limits | Free/Plus/Pro daily and monthly question limits | Numeric config per plan | Decision Required; must preserve Free < Plus < Pro | Product owner | Yes |
| Free mistake repeat policy | Whether Free has limited mistake repeat | Limited access, no full repeat, configurable trial | Decision Required; must align with monetization access table | Product owner | Yes |
| Paywall cooldown | Frequency and suppression rules | No cooldown, per-context cooldown, daily cap | Decision Required; must not show paywall before first value | Product owner | No |
| Admin access model | Locked: owner-only Telegram admin commands | Static admin allowlist, role-based auth, provider auth | Closed in `docs/16_architecture_lock.md`; implementation still required in later milestone | Tech owner / Ops owner | No for coding; Yes before production |
| Analytics backend | Locked: PostgreSQL `analytics_events` | Internal DB, external analytics provider, hybrid | Closed in `docs/16_architecture_lock.md`; event writes/reports remain later milestone work | Product owner / Tech owner | No |
| Analytics events | Final event registry and metadata | Docs event registry plus API operational events | Use docs/10 registry as baseline; add only approved operational events | Product owner / Data owner | Yes before analytics milestone |
| Monitoring stack | Exact metrics, logs and alerts tooling | Provider monitoring, self-hosted stack, hosted observability | Operations model is locked; concrete monitoring implementation remains required before production | Ops owner | Yes before production |
| Backup policy | Frequency, retention, storage and restore cadence | Daily, more frequent payment-critical backup, provider snapshots | Decision Required; restore test is mandatory before production | Ops owner | Yes before production |
| QA tooling | Locked baseline: pytest + pytest-asyncio | Stack-specific unit/integration/E2E tools | Closed for current Python implementation; contract/E2E/security gates still need implementation | Tech owner / QA owner | No for coding; Yes before release |
| Production release owner | Who approves production readiness | Product owner, tech owner, ops owner | Decision Required; production checklist needs accountable owner | Product owner | Yes |

## 4. Milestone 0 — Architecture Lock

Перед написанням коду потрібно зафіксувати production architecture baseline.

Scope:

- implementation stack;
- Telegram bot framework;
- repository structure;
- module boundaries;
- config strategy;
- secrets strategy;
- database strategy;
- migration strategy;
- deployment model;
- Telegram webhook or polling mode;
- Quiz Bank API integration contract;
- cache policy;
- payment model;
- subscription configuration model;
- analytics storage/reporting model;
- admin access model;
- monitoring and backup model.

Acceptance criteria:

- усі locked blocking decisions із секції `Architecture Decisions and Remaining Required Decisions` закриті;
- рішення не суперечать product logic, use cases, domain model, progress model, monetization, API integration, data standard, analytics, security, QA і operations;
- визначено, де зберігаються secrets і як вони ротуються;
- визначено, як production deployment буде repeatable, auditable і reversible;
- визначено, як Telegram Stars payment буде verified і credited idempotently;
- roadmap можна виконувати без зміни продуктової логіки.

## 5. Milestone 1 — Repository and Foundation

Результат milestone: робоча production-grade основа репозиторію без бізнес-логіки, але з повною структурою для реалізації.

Scope:

- створити stack-specific source layout;
- виділити app modules: bot handlers, sessions, progress, mistakes, subscriptions, payments, Quiz Bank API client, analytics, admin, config, persistence, logging;
- додати typed configuration layer з fail-fast validation для production;
- визначити `.env.example` або інший non-secret template без реальних секретів;
- налаштувати dependency management і lockfile після вибору stack;
- додати structured logging з redaction policy;
- додати centralized error handling і safe German fallback copy registry;
- підготувати Dockerfile і Docker Compose для локального runtime, database і test dependencies;
- додати CI checks для lint, type checks, tests, markdown/static checks і secret scanning;
- додати базові health endpoints або health commands відповідно до deployment model.

Acceptance criteria:

- app стартує локально з non-production config;
- production startup fails fast без required config;
- secrets не комітяться і не логуються;
- CI запускає визначені checks;
- module boundaries відповідають docs/02 NFR-040.

## 6. Milestone 2 — Database and Data Layer

Результат milestone: schema, repositories і transaction boundaries для всього production domain.

Scope:

- users;
- training_sessions;
- training_session_items;
- question_references;
- user_answers;
- progress_topics;
- progress_history;
- mistakes;
- mistake_history;
- recommendations;
- daily_limits;
- subscriptions;
- payments;
- analytics_events;
- api_error_logs;
- admin/audit logs if admin access requires them;
- migrations with reviewed schema changes;
- foreign keys, unique constraints and idempotency constraints;
- indexes for user lookup, active sessions, progress by user/level/theme, active mistakes, daily limits, payments, subscriptions, analytics by event/time and API errors;
- transaction helpers for question shown, answer accepted, payment credit and progress recalculation;
- backup compatibility and restore validation assumptions.

Acceptance criteria:

- duplicate Telegram update cannot create a second accepted answer;
- duplicate payment event cannot create a second credited subscription period;
- Daily Limit can be charged once per shown training session item;
- append-only history tables are available for progress and mistakes;
- migration rollback notes or forward-fix policy exist;
- schema supports backup/restore without breaking payment idempotency.

## 7. Milestone 3 — Core Telegram Bot

Результат milestone: Telegram shell with complete navigation and safe states.

Scope:

- `/start` for new and returning users;
- automatic user creation and returning user recognition;
- onboarding with German copy;
- main menu with `▶️ Üben`, `🎯 Niveau & Thema`, `📊 Mein Fortschritt`;
- level selection A1, A2, B1, B2, C1;
- theme selection with availability-driven list;
- profile/progress entry;
- subscription/paywall entry points where allowed;
- Home return behavior;
- safe fallback messages for unknown or expired callback;
- callback ownership checks;
- duplicate callback protection;
- German-only copy registry and copy QA hooks.

Acceptance criteria:

- user-facing bot copy is German;
- new user is not duplicated;
- returning user reaches Home;
- unsupported callback does not corrupt state;
- user cannot act on another user context;
- Home has only the primary navigation actions defined in UX docs.

## 8. Milestone 4 — Quiz Bank API Integration

Результат milestone: validated Quiz Bank API client ready for production flows.

Scope:

- API client with base URL, auth headers, request id and user agent;
- server-side API key handling;
- health endpoint support;
- levels endpoint support;
- themes endpoint support;
- availability endpoint support;
- question batch endpoint support;
- question lookup endpoint support;
- metadata endpoint support;
- quiz request contract for level, theme, count, exclude_seen, exclude_item_ids, item_ids and session_type;
- level/theme filters;
- schema and semantic response validation;
- retry policy for safe read endpoints;
- timeout policy with UX budget;
- error taxonomy handling;
- cache policy for levels, themes, availability, metadata and active session question buffer;
- circuit breaker behavior;
- technical API error logging;
- fallback behavior that never creates fake progress.

Acceptance criteria:

- invalid API payloads are rejected before use;
- questions are not shown without item_id, level, theme, answer_options, correct_answer, explanation and metadata;
- API failure does not charge daily limit;
- API failure does not create User Answer or Mistake;
- insufficient questions follow configured policy;
- bot does not duplicate full Quiz Bank content.

## 9. Milestone 5 — Training Session Engine

Результат milestone: full training loop from session creation to result.

Scope:

- session creation for regular, recommended and mistake_review session types;
- question batch preparation;
- training_session_items lifecycle: prepared, shown, answered, skipped, invalid;
- quiz delivery with position indicator;
- answer handling and scoring;
- explanation display after correct/incorrect answer;
- next question flow;
- finish screen with correct count, percentage, weak theme, new mistakes and recommendation;
- session resume or safe continuation policy;
- explicit abandon handling through Home;
- duplicate answer protection;
- ownership checks;
- idempotent answer processing;
- Daily Limit charge only after question is shown.

Acceptance criteria:

- one answer per question per session;
- completed session does not accept new answers;
- answer transaction updates session counters, progress, mistakes, history and analytics atomically;
- API failure before shown question does not create learning data;
- result screen is shown only for valid completed sessions.

## 10. Milestone 6 — Progress System

Результат milestone: production progress model implemented and visible to users.

Scope:

- total progress by level;
- level progress across all available topics, including topics without answers;
- theme progress per user + level + theme;
- accuracy;
- coverage using unique item_id and available_items_count;
- coverage unknown handling;
- stability using repeated answers across Europe/Berlin days;
- weakness formula;
- recency risk;
- topic status: new, weak, learning, stable, strong;
- streaks if defined in product configuration; otherwise mark exact streak policy as Decision Required;
- weak areas;
- completed sessions;
- learning history through progress_history;
- progress screen with strong themes, weak themes and recommendation;
- deterministic recalculation and tests.

Acceptance criteria:

- high accuracy alone cannot make a topic strong;
- coverage unknown prevents strong;
- weak overrides positive signals when repeated mistakes exist;
- progress is separated across A1, A2, B1, B2, C1;
- user sees a German progress screen understandable in 10 seconds.

## 11. Milestone 7 — Mistakes and Review

Результат milestone: mistakes become a complete learning loop.

Scope:

- mistake capture on wrong accepted answer;
- active mistake uniqueness per user + item_id;
- mistake statuses: new, repeated, improved, resolved;
- mistake_history append-only events;
- repeat wrong answers;
- weak theme detection based on mistakes and progress;
- review mode with session_type = mistake_review;
- correct repeat handling;
- resolution threshold: successful_repeats_count >= 3, successful_repeat_days_count >= 2, and last_mistake_at before successful repeat sequence;
- resolved mistake reopening after new wrong answer;
- content_unavailable handling for old Quiz Bank items;
- progress impact on stability and weakness;
- anti-random-answer logic only if defined before coding; otherwise Decision Required.

Acceptance criteria:

- one correct repeat does not resolve a mistake;
- wrong after resolved reopens the mistake;
- mistake review updates Progress Topic and history;
- unavailable Quiz Bank item does not delete the mistake or show invalid content;
- mistake screen has German empty and active states.

## 12. Milestone 8 — Limits, Entitlements and Subscriptions

Результат milestone: access control works for Free, Plus, Pro and expired subscriptions.

Scope:

- Free limits;
- Plus access;
- Pro access;
- daily quiz limits;
- monthly quiz limits only if product owner defines them before coding; otherwise Decision Required;
- Free < Plus < Pro limit hierarchy;
- entitlement checks for full progress, topic detail, mistake journal, mistake repeat, recommendations, advanced statistics and personal plan if enabled;
- backend/service-layer access checks independent of UI;
- expired subscription handling;
- no data loss after expiration;
- subscription status screen;
- pending subscription does not unlock paid access;
- paywall only after allowed value moments;
- paywall cooldown if configured.

Acceptance criteria:

- paid feature access requires entitlement;
- active paid access requires active subscription and credited payment;
- expired paid user returns to Free access without losing progress, mistakes, payments or subscription history;
- Free limit hit shows German paywall and records analytics;
- Pro includes Plus and Plus includes Free.

## 13. Milestone 9 — Payments

Результат milestone: Telegram Stars payments safely activate subscriptions.

Scope:

- Telegram Stars payment flow;
- plan selection for Plus and Pro;
- invoice creation;
- Payment record creation before invoice;
- payment confirmation handling;
- provider reference and idempotency key;
- expected user, plan and amount verification;
- idempotent credit;
- failed payment behavior;
- cancelled payment state if applicable to Telegram Stars flow;
- refund/cancel state if applicable to final provider behavior; otherwise Decision Required;
- subscription activation after credited payment;
- payment audit log;
- payment analytics events;
- safe German success/failure copy;
- duplicate provider event handling.

Acceptance criteria:

- payment failure does not activate access;
- payment success alone does not unlock paid features until credit is applied;
- one provider payment id credits at most one subscription period;
- provider debug payloads and secrets are not logged or shown;
- Plus/Pro durations and prices come from approved launch configuration.

## 14. Milestone 10 — Analytics and Admin Metrics

Результат milestone: product, learning, monetization and operational analytics are available.

Scope:

- onboarding events: bot_started, user_created, level_selected, theme_selected;
- quiz started: training_started;
- quiz answered: question_answered;
- session completed: training_completed and result_shown;
- level/theme selected events;
- progress_opened;
- mistakes_opened and mistakes_repeated;
- recommendation_shown if recommendation is shown as a tracked event;
- daily_limit_hit;
- subscription viewed or paywall/subscription screen events as approved in tracking plan;
- payment started;
- payment completed: payment_succeeded and subscription_started;
- payment_failed;
- subscription_expired;
- retention metrics: day 1, day 7, day 30;
- conversion metrics: paywall CTR, payment success, Free to Plus, Plus to Pro, expiration recovery;
- API operational analytics;
- admin dashboard requirements or admin reports for total users, active users, sessions, answers, subscriptions, payments, API errors, payment errors and learning metrics.

Acceptance criteria:

- analytics events are append-only and privacy-safe;
- missing analytics write does not break user flow;
- subscription purchase metrics use credited subscription state;
- paywall_clicked can be attributed to paywall_shown;
- admin metrics are protected by authentication and authorization.

## 15. Milestone 11 — Security and Abuse Protection

Результат milestone: production security controls are implemented and tested.

Scope:

- secrets stored outside committed files;
- Telegram bot token protection;
- Quiz Bank API key protection;
- payment credentials protection;
- webhook security with HTTPS and secret verification if webhook mode is selected;
- Telegram update validation and duplicate handling;
- callback ownership checks;
- user data ownership checks;
- admin authentication and authorization;
- rate limits for `/start`, training start, answer callbacks, retry, paywall click, payment start and admin endpoints;
- payment fraud/replay protection through provider verification and idempotency;
- user data minimization;
- logs without secrets, raw provider payloads, raw API responses or stack traces in user-facing messages;
- analytics redaction/rejection for secret fields;
- backup encryption and restricted access;
- incident response controls.

Acceptance criteria:

- user cannot access another user's progress, mistakes, session or payment;
- admin endpoints reject unauthenticated and unauthorized requests;
- duplicate Telegram updates and duplicate payment events do not corrupt state;
- no secrets appear in logs, analytics, Telegram messages or committed files;
- security QA checks pass.

## 16. Milestone 12 — Operations and Deployment

Результат milestone: production can be deployed, observed, restored and rolled back.

Scope:

- hosting target selected;
- Docker deployment;
- production database provisioned;
- Telegram webhook setup or approved polling mode;
- environment separation: local, staging, production;
- required env variables configured;
- protected secret injection;
- monitoring for bot, Telegram updates, DB, Quiz Bank API, payments, subscriptions, backups and admin auth failures;
- structured logs and retention policy;
- encrypted backups;
- restore test;
- rollback plan;
- incident response process;
- production smoke tests after deploy;
- admin metrics protected and available.

Acceptance criteria:

- production deploy has preflight, execution and post-deploy verification;
- backup is not considered valid until restore is tested;
- rollback target is known before deploy;
- payment credit and learning data integrity are verified after deploy/rollback;
- production readiness blockers from docs/13 are closed.

## 17. Milestone 13 — QA and Test Strategy

Результат milestone: release is blocked unless critical QA gates pass.

Scope:

- unit tests for progress formulas, topic status, recommendation, access rules and payment idempotency;
- integration tests for answer to progress to mistake to analytics flow;
- Telegram flow tests for `/start`, onboarding, level/theme, training, result, progress, mistakes, paywall and subscription;
- API integration tests and contract tests;
- API failure tests for timeout, invalid response, insufficient questions and unavailable content;
- payment tests for invoice creation, success, failure, cancellation if applicable, duplicate event and amount/plan/user mismatch;
- subscription tests for active, pending, expired, renewal and no data loss;
- progress tests for accuracy, coverage, stability, weakness, recency and history;
- mistake tests for lifecycle, review and resolution;
- security checks for ownership, admin access, secrets, logs, analytics and rate limits;
- regression checklist;
- German copy checks;
- production release gates with QA evidence.

Acceptance criteria:

- all critical test categories pass;
- failed critical tests block release unless explicitly documented and accepted by owner;
- test fixtures contain no real secrets, real payment credentials, real personal data or production Quiz Bank dump;
- QA evidence records scope, environment, build/commit, result, failures, risks and timestamp.

## 18. Full Production Completion Checklist

- [ ] Bot works end-to-end from `/start` to onboarding, level, theme, training, result, progress and mistake review.
- [ ] Telegram UI copy is German across onboarding, menus, questions, feedback, progress, mistakes, paywall, payments and errors.
- [ ] Quiz Bank API integration is stable, validated and monitored.
- [ ] Bot does not duplicate Quiz Bank as a local question bank.
- [ ] API failure does not create answers, mistakes, progress or daily limit charge.
- [ ] Database schema supports users, sessions, session items, answers, progress, history, mistakes, subscriptions, payments, limits, analytics and API errors.
- [ ] Answer processing is idempotent.
- [ ] Payment credit is idempotent.
- [ ] Payments tested with Telegram Stars test/prod configuration as approved.
- [ ] Subscriptions tested for Free, Plus, Pro, pending, active, expired and renewal.
- [ ] Progress tested for accuracy, coverage, stability, weakness, recency and topic status.
- [ ] Mistakes tested for creation, repeat, improved, resolved and reopened states.
- [ ] Limits tested for Free, Plus, Pro and Europe/Berlin reset.
- [ ] Entitlements enforce paid features in service layer and UI.
- [ ] Analytics available for activation, retention, sessions, progress, mistakes, paywall, payments, subscriptions and API diagnostics.
- [ ] Admin metrics available and protected.
- [ ] Monitoring active for bot, DB, Quiz Bank API, payments, subscriptions, logs and backups.
- [ ] Backup configured, encrypted and access-controlled.
- [ ] Backup/restore tested.
- [ ] Security checks passed.
- [ ] Logs and analytics contain no secrets.
- [ ] Rate limits active for abuse-sensitive actions.
- [ ] Rollback plan ready and tested where feasible.
- [ ] Production smoke tests defined and passing.
- [ ] Documentation complete for config, deploy, operations, QA, incident response and open decisions.
- [ ] All blocking decisions are closed.

## 19. Risks and Mitigations

| Risk | Impact | Mitigation | Owner | Status |
|---|---|---|---|---|
| Architecture decisions drift from locked stack | Coding can reintroduce stack or boundary ambiguity | Keep `docs/16_architecture_lock.md`, `.agent/project/PROJECT_CONTEXT.md`, and `.agent/project/CODE_STYLE.md` aligned before execution work | Tech owner | Controlled |
| Quiz Bank API contract incomplete | Sessions, progress coverage and mistake review may be unstable | Finalize contract, mocks and contract tests before training engine | API owner / Tech owner | Open |
| Prices or durations undefined | Payments and subscriptions cannot be configured safely | Product owner defines launch configuration before payment coding | Product owner | Open |
| Telegram Stars details misunderstood | Payment credit or invoice flow may fail in production | Validate provider flow in test mode and document payload/idempotency | Tech owner | Open |
| Daily limits undefined | Entitlement behavior cannot be tested fully | Define Free/Plus/Pro limits with hierarchy before coding access checks | Product owner | Open |
| API failures corrupt learning state | Fake progress or wrong limit charge | Enforce transaction ordering and API failure tests | Tech owner / QA owner | Open |
| Duplicate Telegram updates | Duplicate answers, progress or limits | Idempotency keys and unique constraints for updates and answers | Tech owner | Open |
| Duplicate payment events | Duplicate paid access | Payment credit transaction and provider_payment_id uniqueness | Tech owner | Open |
| Coverage unavailable from Quiz Bank | Topic status may be misleading | Support coverage unknown and block strong status without count | Tech owner / API owner | Open |
| Admin surface exposed | Sensitive operational or user data leak | Auth, authorization, audit logs and aggregate-by-default dashboards | Ops owner / Tech owner | Open |
| Secrets leak in logs or docs | Security incident | Redaction, secret scanning, review gates and runtime secret injection | Ops owner | Open |
| Backup not restorable | Production data loss after incident | Restore test before launch and recurring restore checks | Ops owner | Open |
| Rollback unsafe after migrations | Data or payment inconsistency | Migration review, rollback notes, forward-fix policy and smoke tests | Tech owner / Ops owner | Open |
| German copy regression | Product violates German-only rule | Copy registry and German copy QA checks | Product owner / QA owner | Open |
| Analytics gaps | Activation, retention or conversion cannot be trusted | Tracking plan, event tests and data quality checks | Data owner | Open |

## 20. Execution Order

1. Maintain Milestone 0 Architecture Lock and keep project context/style aligned with locked decisions.
2. Define launch configuration placeholders and owners for unresolved product config: prices, durations, limits, paywall cooldown, Free mistake repeat policy and Telegram Stars production settings.
3. Build Milestone 1 Repository and Foundation.
4. Build Milestone 2 Database and Data Layer, including migrations, constraints, indexes and transaction helpers.
5. Build Milestone 4 Quiz Bank API Integration before relying on live quiz content in bot flows.
6. Build Milestone 3 Core Telegram Bot navigation and safe callback handling.
7. Build Milestone 5 Training Session Engine with answer idempotency and Daily Limit charge ordering.
8. Build Milestone 6 Progress System and validate formulas against docs/05.
9. Build Milestone 7 Mistakes and Review with history and resolution thresholds.
10. Build Milestone 8 Limits, Entitlements and Subscriptions with service-layer enforcement.
11. Build Milestone 9 Payments after Telegram Stars config, prices and durations are approved.
12. Build Milestone 10 Analytics and Admin Metrics across learning, monetization and operations.
13. Build Milestone 11 Security and Abuse Protection controls, then run security QA.
14. Build Milestone 12 Operations and Deployment, including staging, monitoring, backup, restore and rollback.
15. Complete Milestone 13 QA and Test Strategy across all critical paths.
16. Run the Full Production Completion Checklist.
17. Run staging smoke tests with safe credentials.
18. Verify backup restore and rollback readiness.
19. Approve production release only after all blockers and critical QA failures are closed or explicitly accepted by the responsible owner.
20. Deploy production and run post-deploy smoke tests for Telegram, Quiz Bank API, training, progress, mistakes, payments, admin metrics, logs and monitoring.
