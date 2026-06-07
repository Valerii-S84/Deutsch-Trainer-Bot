# Deutsch Trainer Bot — Operations

## 1. Document Purpose

Цей документ описує експлуатацію **Deutsch Trainer Bot**.

Він фіксує:

* deployment;
* environment variables;
* monitoring;
* backup;
* rollback;
* incident response;
* admin metrics;
* production checklist.

Документ не є infrastructure-as-code, CI/CD pipeline, hosting decision або production runbook для конкретного провайдера.

Його мета — задати строгий, перевірюваний і презентаційно зрозумілий operations standard, який можна перетворити на deployment runbook, release checklist, monitoring dashboard і incident process після вибору технічного стеку.

---

## 2. Operations Standard

Operations описані в строгому академічному форматі.

У межах цього документа **Stanford-level standard** означає:

* кожне production dependency має ownership і health rule;
* кожен deploy має preflight, execution і post-deploy verification;
* кожна environment variable має purpose і sensitivity class;
* кожен secret зберігається поза репозиторієм;
* кожна critical metric має monitoring rule;
* кожен backup має restore rule;
* кожен rollback має trigger і safety rule;
* кожен incident має severity, response і evidence rule;
* кожен admin metric має operational purpose;
* production не вважається ready без checklist completion.

Головний принцип:

> Production має бути відновлюваним, спостережуваним і безпечним до того, як бот отримає реальних користувачів і платежі.

---

## 3. Operational Scope

## 3.1. Production Components

Release 1 production має включати:

| Component | Purpose |
|---|---|
| Telegram bot runtime | Обробка user messages і callbacks. |
| Persistent data store | Users, sessions, answers, progress, mistakes, subscriptions, payments. |
| Quiz Bank API client | Отримання навчального контенту. |
| Payment integration | Telegram Stars payment flow. |
| Admin metrics surface | Базова статистика й operational diagnostics. |
| Logging | Technical diagnostics and incident review. |
| Monitoring | Availability, latency, errors, payment/API health. |
| Backup storage | Recovery for product and payment-critical data. |

## 3.2. Out of Scope

Цей документ не визначає:

* cloud provider;
* container platform;
* database engine;
* CI/CD vendor;
* exact deploy commands;
* exact backup retention period;
* production hostnames;
* real credentials;
* cost model.

---

## 4. Deployment

## 4.1. Deployment Principle

Deployment має бути repeatable, auditable і reversible.

Production deploy не виконується без прямого запиту й готового production checklist.

## 4.2. Deployment Environments

Рекомендовані середовища:

| Environment | Purpose |
|---|---|
| `local` | Development and isolated testing. |
| `staging` | Pre-production verification with safe credentials. |
| `production` | Real users, real payments, real data. |

Якщо staging відсутній, production deploy має бути blocked або явно approved as risk.

## 4.2.1. Repo-Side Deployment Artifacts

Milestone 12 repo-side deployment artifacts:

| Artifact | Purpose |
|---|---|
| `docker-compose.production.yml` | Standalone production Compose definition for bot, PostgreSQL, Redis and Caddy. |
| `deploy/Caddyfile.production.template` | Caddy HTTPS reverse proxy template without committed real domain. |
| `deploy/env.production.template` | Production environment variable template without committed secrets. |
| `deploy/env.staging.template` | Staging environment variable template without committed secrets. |
| `scripts/ops_preflight.sh` | Non-deploy preflight validation for config, Compose, DB and Redis. |
| `scripts/ops_smoke.sh` | Non-mutating HTTP, Telegram and Quiz Bank smoke checks. |
| `docs/20_operations_deployment_runbook.md` | Concrete pre-deploy, deploy, smoke, rollback and incident response runbook. |

These artifacts do not prove production readiness without target-environment
evidence from staging or production.

## 4.3. Deployment Preflight

Перед deploy потрібно перевірити:

* code version identified;
* migrations or data changes reviewed, if any;
* environment variables present;
* secrets loaded from protected storage;
* Telegram bot token configured;
* Quiz Bank API access works;
* payment provider test or production mode explicitly known;
* database reachable;
* backup exists or initial backup policy is active;
* monitoring endpoints available;
* rollback target known;
* release quality gates passed.

## 4.4. Deployment Execution Rule

Deploy має:

* не друкувати secrets;
* не змінювати production data вручну без окремого approval;
* не bypass-ити test gates без documented risk;
* не активувати paid access logic без payment verification;
* не змінювати Quiz Bank ownership boundary.

## 4.5. Post-Deploy Verification

Після deploy потрібно перевірити:

| Check | Expected Result |
|---|---|
| Bot health | Runtime accepts Telegram updates. |
| `/start` flow | User can reach Home or onboarding. |
| Quiz Bank API | Health and question fetch work. |
| Training session | Question can be shown and answered. |
| Progress update | Accepted answer updates progress. |
| Mistake creation | Wrong answer creates mistake. |
| Payment flow | Payment screen can be opened safely. |
| Admin metrics | Protected admin metrics load. |
| Logs | Errors are structured and no secrets appear. |
| Monitoring | Core alerts and dashboards receive data. |

---

## 5. Environment Variables

## 5.1. Purpose

Environment variables configure runtime behavior without committing secrets or production-specific values.

## 5.2. Required Configuration Groups

| Group | Purpose |
|---|---|
| Runtime | Environment, timezone, log level. |
| Telegram | Bot token, webhook or polling mode. |
| Quiz Bank API | Base URL, API key, timeout. |
| Database | Connection string or credentials. |
| Payment | Telegram Stars/payment provider settings. |
| Admin | Admin auth and access configuration. |
| Analytics | Analytics backend or internal event config. |
| Backup | Backup target and credentials. |

## 5.3. Environment Variable Registry

Recommended logical variables:

| Variable | Required | Sensitive | Purpose |
|---|---:|---:|---|
| `APP_ENV` | Yes | No | `development`, `staging`, `production`. |
| `APP_TIMEZONE` | Yes | No | Must be `Europe/Berlin` for business-day logic. |
| `LOG_LEVEL` | Yes | No | Runtime logging level. |
| `BOT_TOKEN` | Yes | Yes | Telegram Bot API access. |
| `BOT_WEBHOOK_ENABLED` | Production | No | Must be true for production webhook runtime. |
| `TELEGRAM_WEBHOOK_URL` | If webhook | No | HTTPS public origin; exact production FQDN lives in deploy inventory, not committed docs. |
| `TELEGRAM_WEBHOOK_PATH` | If webhook | No | Locked Release 1 path: `/telegram/webhook`. |
| `TELEGRAM_WEBHOOK_SECRET` | If webhook | Yes | Webhook verification, if used. |
| `QUIZ_BANK_API_BASE_URL` | Yes | No | Quiz Bank API host. |
| `QUIZ_BANK_EDGE_API_KEY` | Yes | Yes | Edge/API gateway auth. |
| `QUIZ_BANK_CONSUMER_ID` | Yes | No | Consumer identity for Quiz Bank access. |
| `QUIZ_BANK_CONSUMER_API_KEY` | Yes | Yes | Consumer API auth. |
| `QUIZ_BANK_TIMEOUT_SECONDS` | Yes | No | API timeout. |
| `QUIZ_BANK_MAX_RETRIES` | Yes | No | Safe read retry budget. |
| `DATABASE_URL` | Yes | Yes | Data store connection. |
| `REDIS_URL` | Production | Yes | Redis-backed global rate limits and duplicate update guard. |
| `SECURITY_STATE_BACKEND` | Yes | No | `auto` locally; Redis outside development. |
| `SECURITY_RATE_LIMIT_ENABLED` | Yes | No | Enables abuse-sensitive rate limits. |
| `TELEGRAM_STARS_MODE` | Yes | No | `test` or `prod`; production launch must set `prod`. |
| `PLUS_PRICE_STARS` | Yes | No | Release 1 default: `10`. |
| `PRO_PRICE_STARS` | Yes | No | Release 1 default: `20`. |
| `PLUS_DURATION_DAYS` | Yes | No | Release 1 default: `30`. |
| `PRO_DURATION_DAYS` | Yes | No | Release 1 default: `90`. |
| `FREE_DAILY_QUESTION_LIMIT` | Yes | No | Release 1 default: `5`. |
| `PLUS_DAILY_QUESTION_LIMIT` | Yes | No | Release 1 default: `25`. |
| `PRO_DAILY_QUESTION_LIMIT` | Yes | No | Release 1 default: `100`. |
| `PAYWALL_COOLDOWN_POLICY` | Yes | No | Release 1: `none`. |
| `ADMIN_TELEGRAM_USER_IDS` | Yes | Sensitive | Owner-only Telegram admin allowlist. |
| `BACKUP_STORAGE_URL` | Production | Sensitive | Backup destination. |
| `BACKUP_STORAGE_SECRET` | Production | Yes | Backup storage access. |

## 5.4. Secret Rules

Secrets must:

* live outside committed files;
* be injected at runtime;
* be redacted in logs;
* be rotatable without code changes;
* never appear in Telegram messages, analytics events or Markdown docs.

## 5.5. Configuration Validation

Application startup should fail fast if:

* required production variable is missing;
* `APP_ENV=production` is not configured for webhook mode;
* `APP_ENV=production` uses `SECURITY_STATE_BACKEND=in_memory`;
* `APP_ENV=production` uses `TELEGRAM_STARS_MODE=test` for real launch;
* production has no database configuration;
* production has no Redis configuration for global security state;
* production has no backup configuration;
* Quiz Bank API timeout is missing;
* admin owner allowlist is not configured.

---

## 6. Monitoring

## 6.1. Monitoring Purpose

Monitoring має показувати:

* чи бот доступний;
* чи працює Quiz Bank API;
* чи проходять тренувальні сесії;
* чи зберігаються відповіді;
* чи працюють платежі;
* чи є API/payment errors;
* чи не ростуть duplicate або idempotency problems;
* чи backup виконується.

## 6.2. Health Checks

Required health checks:

| Check | Purpose |
|---|---|
| Bot runtime health | Process is running. |
| Telegram connectivity | Bot can receive or poll updates. |
| Database health | Data store reachable. |
| Quiz Bank health | External content API reachable or degraded state known. |
| Payment readiness | Payment provider config present. |
| Admin surface health | Protected admin metrics reachable by authorized admin. |

Release 1 monitoring stack:

| Layer | Evidence |
|---|---|
| Container/process | Docker Compose health and restart status. |
| HTTPS edge | Caddy access/error logs and external HTTPS uptime check. |
| Application | Structured app logs with redaction filter enabled. |
| Database | PostgreSQL connectivity and admin metrics queries. |
| Redis | Connectivity check for rate limits and duplicate update guard. |
| Payments/API | Analytics/admin metrics for payment failures, duplicate provider events and Quiz Bank errors. |

## 6.3. Operational Metrics

Monitor:

| Metric | Alert Purpose |
|---|---|
| `bot_errors_rate` | Runtime instability. |
| `telegram_update_failures` | Telegram handling issue. |
| `quiz_api_error_rate` | Quiz Bank instability. |
| `quiz_api_latency_p95` | Slow content delivery. |
| `training_started_count` | Activity baseline. |
| `training_completion_rate` | Product flow health. |
| `answer_write_failures` | Data integrity risk. |
| `daily_limit_charge_errors` | Limit accounting risk. |
| `payment_failed_count` | Payment issue. |
| `payment_duplicate_event_count` | Idempotency pressure. |
| `subscription_credit_failures` | Paid access risk. |
| `admin_auth_failures` | Security signal. |
| `backup_last_success_at` | Recovery readiness. |

## 6.4. Alert Levels

| Level | Meaning | Example |
|---|---|---|
| `info` | Needs observation. | Temporary API degradation. |
| `warning` | Needs operator review. | Elevated payment failures. |
| `critical` | Needs immediate action. | Bot down, database unavailable, payment credit broken. |

## 6.5. Monitoring Safety Rule

Monitoring data must not contain:

* API keys;
* Telegram bot token;
* payment credentials;
* raw provider payloads;
* full user payload dumps;
* raw Authorization headers.

---

## 7. Backup

## 7.1. Backup Scope

Production backup must cover:

* users;
* training sessions;
* training session items;
* question references;
* user answers;
* progress topics;
* progress history;
* mistakes;
* mistake history;
* subscriptions;
* payments;
* daily limits;
* analytics events, if internally stored;
* API error logs, if required for incident review.

## 7.2. Backup Protection

Backups are sensitive data.

Required controls:

* encrypted storage;
* restricted access;
* no public bucket/container;
* credentials outside repository;
* no secrets in backup logs;
* restore access limited to authorized operators.

## 7.3. Backup Frequency

Release 1 frequency:

| Backup type | Minimum cadence |
|---|---|
| Pre-launch baseline | Before enabling production traffic. |
| Pre-change safety backup | Before payment-affecting releases and data/schema changes. |
| Scheduled PostgreSQL backup | Daily after launch. |
| Restore test | Before launch and monthly after launch. |

Minimum retention:

| Window | Retention |
|---|---:|
| Daily backups | 7 |
| Weekly backups | 4 |

Minimum expectation:

| Data | Backup Need |
|---|---|
| User and learning state | Regular backup. |
| Payments and subscriptions | High reliability backup. |
| Analytics events | Backup if internal analytics is source of truth. |
| Logs | Retention by incident policy. |

## 7.4. Restore Test

Backup is not operationally valid until restore is tested.

Restore test must verify:

* users restore correctly;
* progress topics remain linked;
* mistakes and history remain linked;
* payments are not duplicated;
* subscriptions are not credited twice;
* daily limits are not corrupted;
* secrets are not restored into logs or public output.

## 7.5. Backup Failure Handling

If backup fails:

* alert operator;
* mark production readiness degraded;
* investigate storage/auth issue;
* do not silently ignore failure;
* do not perform risky migrations until recovery posture is known.

## 7.6. Repo-Side Backup and Restore Artifacts

Milestone 12 backup artifacts:

| Artifact | Purpose |
|---|---|
| `scripts/postgres_backup.sh` | Creates PostgreSQL custom-format dumps; production mode refuses unencrypted backups. |
| `scripts/postgres_restore_verify.sh` | Restores into a disposable non-production DB and verifies schema and integrity checks. |
| `docs/20_operations_deployment_runbook.md` | Documents retention, encryption, access control and restore verification rules. |

Minimum production rules:

* backup files are sensitive production data;
* production backups must be encrypted;
* backup credentials and encryption private keys stay outside the repository;
* backup logs must not include DB URLs, tokens or encryption secrets;
* retention target is 7 daily backups and 4 weekly backups;
* restore verification is required before launch and monthly after launch.

---

## 8. Rollback

## 8.1. Rollback Purpose

Rollback returns production to a known safer version after a bad deploy.

## 8.2. Rollback Triggers

Rollback should be considered if:

* bot cannot process Telegram updates;
* training sessions cannot start;
* answers cannot be saved;
* progress is corrupted or not updated;
* payments cannot be credited safely;
* duplicate subscriptions are created;
* API integration breaks core training;
* admin metrics expose sensitive data;
* logs expose secrets.

## 8.3. Rollback Precondition

Before rollback, identify:

* current deployed version;
* previous known good version;
* database migration impact;
* payment state impact;
* active incidents;
* whether rollback can worsen data consistency.

## 8.4. Data Safety Rule

Rollback must not:

* duplicate payment credit;
* delete learning data;
* reset user progress incorrectly;
* corrupt daily limits;
* replay Telegram updates unsafely;
* expose secrets in logs.

## 8.5. Post-Rollback Verification

After rollback, verify:

* bot responds;
* existing users can continue;
* answers save correctly;
* daily limits are correct;
* payment idempotency still holds;
* subscriptions remain accurate;
* monitoring shows recovery.

---

## 9. Incident Response

## 9.1. Incident Definition

An incident is any production condition that threatens:

* availability;
* learning data integrity;
* payment correctness;
* user privacy;
* admin access security;
* Quiz Bank integration;
* backup recoverability.

## 9.2. Severity Levels

| Severity | Meaning | Examples |
|---|---|---|
| `SEV1` | Critical production impact. | Bot down, payment credit duplicated, data leak. |
| `SEV2` | Major degraded behavior. | API unavailable for many users, answer writes failing. |
| `SEV3` | Limited issue. | One paywall context broken, admin metric delayed. |
| `SEV4` | Minor operational issue. | Non-critical analytics delay. |

## 9.3. Incident Response Steps

1. Confirm incident.
2. Assign severity.
3. Stop active damage.
4. Preserve evidence.
5. Communicate internal status.
6. Apply mitigation or rollback.
7. Verify recovery.
8. Document root cause.
9. Add prevention item.

## 9.4. Incident Evidence

Incident record should include:

| Field | Purpose |
|---|---|
| `incident_id` | Stable reference. |
| `severity` | SEV level. |
| `started_at` | When issue began. |
| `detected_at` | When detected. |
| `resolved_at` | When resolved. |
| `affected_area` | Bot, API, payment, data, admin, backup. |
| `user_impact` | What users experienced. |
| `root_cause` | Confirmed cause or unknown. |
| `mitigation` | Action taken. |
| `follow_up` | Preventive work. |

## 9.5. Security Incident Rule

If incident involves secrets or user data:

* rotate affected secrets;
* restrict access;
* preserve audit evidence;
* check logs for exposure;
* verify no public backup/log exposure;
* document data impact.

---

## 10. Admin Metrics

## 10.1. Purpose

Admin metrics provide operational visibility without exposing unnecessary personal data.

## 10.2. Required Admin Metrics

Release 1 admin surface must show:

| Metric | Purpose |
|---|---|
| `total_users` | Product size. |
| `active_users_today` | Daily usage. |
| `training_sessions_today` | Training volume. |
| `answers_today` | Learning activity. |
| `payment_count` | Payment activity. |
| `active_subscriptions` | Current paid users. |
| `api_errors_today` | Quiz Bank reliability. |
| `payment_errors_today` | Payment reliability. |

## 10.3. Recommended Learning Metrics

Admin should also see:

| Metric | Purpose |
|---|---|
| popular levels | Demand by CEFR level. |
| popular themes | Topic demand. |
| weak themes | Content or learning difficulty signal. |
| themes with most mistakes | Mistake concentration. |
| mistake repeat count | Whether repeat loop is used. |
| progress opens | Whether progress value is visible. |

## 10.4. Admin Metrics Protection

Admin metrics must:

* require authentication;
* require authorization;
* prefer aggregate data;
* avoid secrets;
* avoid raw payment payloads;
* avoid unnecessary PII;
* audit privileged access.

---

## 11. Logging

## 11.1. Production Log Requirements

Production logs should support:

* request correlation;
* API failure diagnosis;
* payment incident diagnosis;
* admin access audit;
* deploy/rollback traceability.

## 11.2. Forbidden Log Data

Logs must not contain:

* Telegram bot token;
* Quiz Bank API key;
* payment credentials;
* database credentials;
* raw Authorization headers;
* full provider payloads;
* full raw Quiz Bank responses;
* `.env` contents;
* private keys.

## 11.3. Log Retention

Exact log retention is production policy.

Retention must balance:

* incident investigation;
* privacy minimization;
* storage cost;
* payment audit needs.

---

## 12. Production Checklist

## 12.1. Pre-Production Checklist

Before enabling production:

* implementation stack selected;
* database selected and configured;
* Telegram bot token stored in secret storage;
* Quiz Bank API key stored in secret storage;
* payment provider configured;
* admin authentication configured;
* required environment variables configured;
* tests and regression checklist passed;
* backup policy configured;
* restore test completed;
* monitoring configured;
* rollback plan documented;
* incident response owner known;
* user-facing copy verified as German.

## 12.2. Deployment Checklist

Before each deploy:

* release version identified;
* changed scope understood;
* migrations reviewed, if any;
* secrets unchanged or rotated intentionally;
* tests passed;
* backup status checked;
* rollback target known;
* monitoring watched during deploy.

## 12.3. Post-Deployment Checklist

After each deploy:

* bot responds to Telegram;
* `/start` works;
* Quiz Bank API request works;
* training session works;
* answer save works;
* progress update works;
* mistake creation works;
* payment flow does not expose secrets;
* admin metrics load for authorized admin;
* error logs contain no secrets;
* monitoring shows healthy state.

## 12.4. Production Readiness Blockers

Production is blocked if:

* secrets are missing or committed;
* admin endpoints are not protected;
* payments are not idempotent;
* backup is not configured;
* restore was never tested;
* rollback target is unknown;
* Quiz Bank API access is not validated;
* API failure charges daily limit;
* user-facing copy is not German;
* critical tests fail without accepted risk.

## 12.5. Milestone 12 Evidence Gate

Repo-side M12 artifacts close documentation and script gaps only.

Production remains blocked until evidence exists for:

* production domain and HTTPS endpoint;
* Telegram webhook registration in the approved environment;
* protected credential injection without committed secrets;
* staging smoke test with safe credentials;
* monitoring for bot, Caddy, DB, Redis, Quiz Bank, payments, subscriptions,
  admin auth failures, logs and backups;
* encrypted backup creation;
* restore verification on a disposable non-production database;
* rollback target and rollback smoke evidence;
* post-deploy smoke checks.

---

## 13. Operational Acceptance Criteria

Operations standard is acceptable for Release 1 if:

1. Deployment has preflight and post-deploy checks.
2. Environment variable groups and sensitive variables are defined.
3. Monitoring covers bot, API, database, payment and backup health.
4. Backup scope, protection and restore rules are defined.
5. Rollback triggers and safety rules are defined.
6. Incident response has severity levels and response steps.
7. Admin metrics are listed and protected.
8. Production checklist covers pre-production, deploy and post-deploy.
9. Secrets are never stored in committed files or logs.
10. Production deploy remains blocked until explicit production readiness is established.

---

## 14. Operations Invariants

1. Production deploy must be repeatable and reversible.
2. Secrets live outside committed files.
3. Monitoring must detect API, payment and data integrity failures.
4. Backup is not valid until restore is tested.
5. Rollback must not duplicate payments or corrupt learning data.
6. Incidents require evidence and follow-up.
7. Admin metrics are privileged data.
8. Logs must not contain secrets.
9. Production readiness requires tests, backup, monitoring and rollback.
10. Operational controls must protect learning state and payment correctness.
