# Operations Deployment Runbook

This runbook is the concrete Milestone 12 repo-side procedure for staging and
production readiness. It does not approve a real production deploy by itself.

Production remains blocked until external evidence exists for domain ownership,
Telegram webhook registration, protected credentials, monitoring, backup
restore, rollback target, and staging smoke results.

## Repo-Side Artifacts

| Artifact | Purpose |
|---|---|
| `docker-compose.production.yml` | Standalone production Docker Compose definition. |
| `deploy/Caddyfile.production.template` | Caddy HTTPS reverse proxy template with no committed real domain. |
| `deploy/env.production.template` | Production env variable template without secrets. |
| `deploy/env.staging.template` | Staging env variable template without secrets. |
| `scripts/ops_preflight.sh` | Non-deploy preflight validation. |
| `scripts/ops_smoke.sh` | Non-mutating health, Telegram and Local Catalog readiness smoke checks. |
| `scripts/import_local_catalog.py` | Local Quiz Catalog import and dry-run validation from snapshot data sources. |
| `scripts/quiz_bank_live_smoke.py` | Legacy non-gameplay smoke only; not required for training gameplay readiness. |
| `scripts/isolated_runtime_smoke.sh` | Non-mutating Docker smoke checks for isolated polling runtime. |
| `scripts/live_integration_gates.sh` | Manual staging gates for PostgreSQL, Redis, app health, Telegram, Local Catalog and Telegram Stars evidence. |
| `scripts/hardening_load_gates.py` | Capacity, DB pool, duplicate storm, worker lag and Quiz Bank disabled proof gates. |
| `python -m app.workers.run_outbox` | Durable outbox worker for progress, mistakes, analytics and rollups. |
| `scripts/payment_sandbox_evidence_check.py` | Non-secret Telegram Stars sandbox evidence validator. |
| `scripts/git_release_preflight.sh` | Non-mutating git provenance checks before push/release. |
| `scripts/postgres_backup.sh` | PostgreSQL dump with required production encryption. |
| `scripts/postgres_restore_verify.sh` | Disposable restore verification with schema and integrity checks. |
| `docs/21_isolated_server_deploy_inventory.md` | Active isolated server inventory and scoped deploy procedure. |

## Capacity Contract / SLO

Production hardening targets:

| Contract | Target |
|---|---:|
| Registered users | `100000` |
| Active peak users | `5000` |
| Peak answer callbacks | `500/sec` |
| Answer accept latency p95 | `<= 250 ms` app-side, excluding Telegram network delivery |
| Answer accept latency p99 | `<= 750 ms` app-side, excluding Telegram network delivery |
| Error rate | `<= 0.1%` for non-throttled answer callbacks over a 15 minute peak window |
| DB pool wait budget | p95 `<= 50 ms`, p99 `<= 200 ms` |
| Redis latency budget | p95 `<= 10 ms`, p99 `<= 50 ms` |
| Outbox worker lag budget | p95 `<= 30 s`, p99 `<= 120 s`; `dead` events require incident review |

Production-ready is blocked until load evidence proves these budgets in a
staging or production-like environment. Unit tests, local smoke checks and clean
Docker migrations are not enough to claim production readiness.

Required load evidence:

```bash
TEST_DATABASE_URL=<staging-test-db-url> \
python scripts/hardening_load_gates.py seed-users --count 100000

python scripts/hardening_load_gates.py db-pool-saturation \
  --requests 5000 \
  --concurrency 500

TEST_DATABASE_URL=<staging-test-db-url> \
python scripts/hardening_load_gates.py duplicate-storm --concurrency 500

SMOKE_BASE_URL=https://<staging-domain-managed-outside-repo> \
python scripts/hardening_load_gates.py webhook-health-load \
  --base-url "$SMOKE_BASE_URL" \
  --path /ready \
  --requests 5000 \
  --concurrency 500

python scripts/hardening_load_gates.py worker-lag
python scripts/hardening_load_gates.py quiz-bank-disabled-proof
```

The 500 answer callbacks/sec gate must use real signed Telegram-like callback
payloads or an approved internal service-level harness that executes the answer
hot path against PostgreSQL and Redis with Quiz Bank disabled. Record p50, p95,
p99, error rate, DB pool wait, Redis latency, worker lag and duplicate outcome.

Content readiness is tracked separately: the currently selectable `599`
reviewed Local Catalog items remain a Content Readiness risk and must not be
mixed with this technical hardening gate.

## Pre-Deploy Checklist

- Release version and immutable `BOT_IMAGE` are identified.
- `docker-compose.production.yml` renders successfully in the target env.
- Runtime env values are loaded from protected storage, not from committed files.
- `APP_ENV=production`, webhook mode is enabled and polling is disabled.
- `TELEGRAM_WEBHOOK_MAX_CONNECTIONS` is set and recorded.
- `BOT_GLOBAL_IN_FLIGHT_LIMIT` is set below the measured DB/worker capacity.
- `TELEGRAM_STARS_MODE=prod` is configured for production.
- `SECURITY_STATE_BACKEND=redis` is configured outside development.
- PostgreSQL and Redis are reachable from the bot runtime.
- `/ready` returns `ok` for DB and Redis before webhook registration.
- `ACTIVE_CATALOG_ID` is configured for the selected environment.
- Local Quiz Catalog import passed validation and the active catalog exists in
  PostgreSQL.
- Admin allowlist is configured.
- Monitoring targets are configured for bot health, Caddy, DB, Redis, Local Catalog,
  outbox worker lag, payments, subscriptions, admin auth failures, logs and backups.
- DB connection budget is documented:
  `(web_replicas * (DB_POOL_SIZE + DB_MAX_OVERFLOW)) +
  (worker_replicas * (WORKER_DB_POOL_SIZE + WORKER_DB_MAX_OVERFLOW)) +
  admin/script_headroom <= PostgreSQL max_connections - reserved_connections`.
- A recent encrypted backup exists or an initial encrypted backup is created.
- Restore verification passed on a disposable non-production database.
- Rollback target is known before deploy.
- No critical QA gate is failing without documented owner acceptance.

Preflight command:

```bash
bash scripts/ops_preflight.sh
```

Manual staging integration workflow:

```bash
# GitHub Actions: Staging Integration Gates
```

The workflow requires protected staging secrets for PostgreSQL, Redis, bot
token, smoke base URL and `TELEGRAM_STARS_EVIDENCE_JSON`.
The Telegram Stars evidence JSON must contain only non-secret test facts and is
validated by `scripts/payment_sandbox_evidence_check.py`.

Monetization must not be marked production-ready until this evidence exists.
The evidence has to prove a real Telegram Stars test-mode payment path, not only
local unit tests. Required non-secret facts include:

- invoice was created with `invoice_payload_prefix=dtbpay`;
- observed invoice payload hash and payload format matched
  `dtbpay:{payment_id}:{idempotency_key}`;
- pre-checkout was received, matched the payment, and was answered `ok=true`;
- successful payment was delivered and matched the original payment;
- `telegram_payment_charge_id` was present, recorded only as a SHA-256 hash in
  the evidence artifact;
- paid subscription was credited and verified active;
- duplicate provider event handling was verified without a second payment credit
  and without a second subscription period.

Current sandbox status: a 1 Star Telegram Stars test-mode payment was verified
on `2026-07-16` against the isolated server runtime. The sanitized local
artifact is `qa_evidence/telegram_stars_sandbox.json` and is intentionally
gitignored. This does not authorize or prove a production Stars charge; production
mode remains approval-gated.

The evidence artifact must not contain raw payment identifiers, raw invoice
payloads, provider payload dumps, runtime environment values, `BOT_TOKEN`,
database URLs, Redis URLs or credentials. `qa_evidence/` is gitignored and is
the expected local location for the operator-produced sandbox artifact, but the
artifact may be stored in protected inventory instead when local policy requires
that.

Minimal sandbox evidence shape:

```json
{
  "environment": "staging",
  "tested_at": "<ISO-8601 UTC timestamp>",
  "telegram_bot_username": "<bot username only>",
  "telegram_stars_mode": "test",
  "evidence_owner": "<operator or team>",
  "invoice_payload_prefix": "dtbpay",
  "invoice_payload_format": "dtbpay:{payment_id}:{idempotency_key}",
  "invoice_payload_sha256": "<64 lowercase hex sha256>",
  "telegram_payment_charge_id_sha256": "<64 lowercase hex sha256>",
  "credited_plan": "plus",
  "payment_status_after_success": "credited",
  "subscription_status_after_credit": "active",
  "invoice_created": true,
  "invoice_payload_matches_expected_format": true,
  "pre_checkout_received": true,
  "pre_checkout_payload_matched_payment": true,
  "pre_checkout_answered_ok": true,
  "successful_payment_received": true,
  "successful_payment_payload_matched_payment": true,
  "telegram_payment_charge_id_received": true,
  "subscription_credited": true,
  "active_subscription_verified": true,
  "duplicate_event_rejected": true,
  "duplicate_event_no_second_credit": true,
  "duplicate_event_no_second_subscription_period": true
}
```

Sandbox execution procedure:

1. Use only a staging or isolated test runtime with `TELEGRAM_STARS_MODE=test`.
   Do not set `TELEGRAM_STARS_MODE=prod` and do not use the production bot token
   for this gate.
2. Start a Plus or Pro Telegram Stars invoice from the bot UI. Record only that
   the invoice was created and that the observed payload starts with `dtbpay`.
3. Verify the observed invoice payload format locally as
   `dtbpay:{payment_id}:{idempotency_key}`. Do not paste the raw payload into
   docs, logs, commits or chat.
4. Complete the Telegram test-mode payment from the Telegram test account.
5. Verify runtime facts from protected DB access without printing connection
   strings or raw payment rows:
   - the matching payment moved through pre-checkout and successful payment;
   - `payment.status` is `credited`;
   - `telegram_payment_charge_id` is non-empty;
   - the subscription for the payment is `active`;
   - replaying the same provider event is reported as duplicate/idempotent and
     does not create another credit or subscription period.
6. Hash the raw invoice payload and raw `telegram_payment_charge_id` locally with
   SHA-256 and put only the hashes into the artifact.
7. Save the sanitized JSON as `qa_evidence/telegram_stars_sandbox.json` or in
   protected inventory, then validate it:

```bash
python scripts/payment_sandbox_evidence_check.py qa_evidence/telegram_stars_sandbox.json
```

If the validator rejects the artifact, keep the production blocker open. Do not
loosen the validator to fit incomplete evidence.

## Runtime Mode Gate

The default production runtime remains HTTPS webhook with Caddy. Polling is
acceptable only as an explicitly approved isolated runtime exception.

Webhook closure requires:

- `BOT_WEBHOOK_ENABLED=true` and `BOT_POLLING_ENABLED=false`;
- HTTPS `TELEGRAM_WEBHOOK_URL` and `TELEGRAM_WEBHOOK_SECRET` in protected env;
- `TELEGRAM_WEBHOOK_MAX_CONNECTIONS` set to the tested value;
- no silent fallback to polling: incomplete webhook config must fail startup;
- Telegram webhook registration evidence;
- `scripts/ops_preflight.sh` and `scripts/ops_smoke.sh` passing in the target
  environment.

Backpressure closure requires:

- Redis-backed per-user/per-chat throttling outside development;
- global in-flight limit active in dispatcher middleware;
- saturation returns a fast retry response instead of spawning unbounded tasks;
- duplicate Telegram update guard active;
- duplicate answer acceptance also protected by PostgreSQL unique constraints.

Polling exception closure requires:

- explicit operator approval naming polling as the active runtime mode;
- exactly one active bot process for the Telegram token;
- webhook disabled for that bot token before polling starts;
- isolated PostgreSQL and Redis confirmed running;
- active Local Quiz Catalog confirmed imported when the runtime uses gameplay;
- `scripts/isolated_runtime_smoke.sh` passing in the target environment;
- manual Telegram `/start -> menu -> quiz -> question -> answer -> result`
  evidence without running payments;
- a separate token-rotation task after runtime stabilization.

### Isolated Polling Runtime Evidence — 2026-06-04

Operator approved the polling exception for the isolated server runtime.

Scope:

- Deploy path: `/opt/deutsch-trainer-bot/current`.
- Bot: `@Trainer1512_bot`.
- Deployed commit marker: `7847a8d478ffb081d682bafbf020adeb2d46a620`.
- Rebuilt/restarted service: `deutsch-trainer-bot-bot-1` only.
- Not restarted: `deutsch-trainer-bot-db-1`, `deutsch-trainer-bot-redis-1`.
- Old stacks and adjacent services were not touched.
- Payments / Telegram Stars were not run.
- Token rotation was not run.

Runtime evidence:

- Bot container running from image id
  `sha256:1903527f234e843281bcc2af5a6f4c16a345a351da87b4d8169a15b234beca78`.
- DB container running and healthy.
- Redis container running and healthy.
- `scripts/isolated_runtime_smoke.sh` passed with Telegram `getMe`,
  isolated DB schema, Redis ping, required runtime env presence and recent
  bot logs checks.
- Manual Telegram flow passed:
  `/start -> menu -> quiz -> question -> answer -> result`.
- At that time, Quiz Bank connectivity passed through the bot runtime using the
  protected consumer env; after the Local Catalog switch, this evidence is
  legacy and no longer proves gameplay readiness.

Monitoring evidence:

- Bot status: running; restart count `0`.
- DB status: running/healthy; restart count `0`.
- Redis status: running/healthy; restart count `0`.
- Recent sanitized bot logs showed polling startup for `@Trainer1512_bot`
  without traceback or secret output.
- DB counters confirmed existing user, quiz session, training items, answers,
  progress and mistake rows after the manual Telegram flow.

Backup/restore evidence:

- A temporary PostgreSQL custom-format dump was created inside the isolated DB
  container.
- Restore was verified into a disposable temporary database.
- Required restored tables were present:
  `users`, `quiz_sessions`, `training_session_items`, `user_answers`,
  `progress`, `mistakes`, `alembic_version`.
- Restored Alembic version: `202605140002`.
- Temporary restore database and temporary dump file were removed after the
  check.

Rollback target:

- Previous known-good bot image was tagged before rollout as
  `deutsch-trainer-bot:rollback-ec20844-before-daa7a73-20260604`.
- Rollback image id:
  `sha256:6e778b3d211066f123fb45ba578c9c9a8dc29b0b6472aa18a373e6813beed215`.
- Current image id:
  `sha256:1903527f234e843281bcc2af5a6f4c16a345a351da87b4d8169a15b234beca78`.

## Deploy Checklist

- Confirm this is staging or production with the intended protected env store.
- Confirm no command prints env values or secrets.
- Validate Compose config before changing running services.
- Pull or build the approved immutable image outside this runbook.
- Apply database migrations only after backup and rollback review.
- Run Local Quiz Catalog dry-run/import before enabling a new `ACTIVE_CATALOG_ID`.
- Start or update services through Docker Compose.
- Watch bot, Caddy, DB and Redis health checks during rollout.
- Start at least one outbox worker process before accepting production traffic.
- Confirm outbox worker lag is within budget before and after webhook traffic.
- Do not register or change a production Telegram webhook without explicit
  operator approval.

Local Catalog import command template:

```bash
python scripts/import_local_catalog.py \
  --source-path "${CATALOG_SOURCE_PATH:-ProductionQuizBank}" \
  --catalog-id "<new-catalog-id>" \
  --catalog-version "<snapshot-version>" \
  --dry-run

python scripts/import_local_catalog.py \
  --source-path "${CATALOG_SOURCE_PATH:-ProductionQuizBank}" \
  --catalog-id "<new-catalog-id>" \
  --catalog-version "<snapshot-version>"
```

Compose validation command:

```bash
docker compose -f docker-compose.production.yml config --quiet
```

## Git Release Provenance Gate

GitHub repository creation and branch push are separate operator actions. Do not
push into a lookalike or unrelated repository.

Before first push:

- create the correct project GitHub repository;
- configure `origin` to that repository only;
- keep work on a feature branch, not `main`;
- keep the worktree clean;
- run the local QA release gates;
- run the git preflight.

Git preflight command:

```bash
EXPECTED_BRANCH=chore/phase-0-1-foundation \
bash scripts/git_release_preflight.sh
```

After the preflight passes, push only the current feature branch to the verified
remote. Merge, squash or rebase still requires the project merge decision.

## Post-Deploy Smoke Checklist

- `/health` returns `{"status": "ok"}` through HTTPS.
- `/ready` returns DB pool wait and Redis latency within budget.
- Telegram `getMe` succeeds with the environment bot token.
- Telegram webhook delivery is confirmed by external deployment evidence.
- Active Local Quiz Catalog exists in PostgreSQL and selection smoke succeeds.
- `/start` works in Telegram.
- Level, theme and training start work with safe smoke data.
- Answer save responds quickly; progress, analytics and mistake creation are
  observed through outbox worker processing, not the callback hot path.
- Payment flow does not expose secrets; real payment credit is only verified in
  approved Telegram test or production mode.
- Admin metrics load only for an authorized admin.
- Logs, analytics and smoke output contain no secrets.
- Monitoring shows bot, DB, Redis, Local Catalog, payment and backup health.
- Monitoring shows outbox pending/processing/failed/dead counts and worker lag.

Smoke command template:

```bash
SMOKE_BASE_URL=https://<deployment-domain-managed-outside-repo> \
RUN_TELEGRAM_SMOKE=1 \
RUN_LOCAL_CATALOG_SMOKE=1 \
bash scripts/ops_smoke.sh
```

Live integration gate template:

```bash
RUN_TELEGRAM_SMOKE=1 \
RUN_LOCAL_CATALOG_SMOKE=1 \
ACTIVE_CATALOG_ID=<imported-catalog-id> \
TELEGRAM_STARS_EVIDENCE_FILE=qa_evidence/telegram_stars_sandbox.json \
bash scripts/live_integration_gates.sh
```

When `RUN_LOCAL_CATALOG_SMOKE=1`, the staging gate must prove that
`ACTIVE_CATALOG_ID` points to an imported active catalog, selectable rows exist
for enabled levels, and gameplay does not read snapshot CSV files directly.

Legacy Quiz Bank smoke may still run for non-gameplay diagnostics, but it is not
required for Deutsch Trainer training gameplay readiness.

Isolated polling runtime smoke template:

```bash
RUN_TELEGRAM_SMOKE=1 \
bash scripts/isolated_runtime_smoke.sh
```

## Backup Procedure

- Use encrypted PostgreSQL backups for production.
- Store backups outside the repository with restricted filesystem and operator
  access.
- Do not print `DATABASE_URL`, backup credentials, tokens or encryption keys.
- Minimum retention for Release 1 is 7 daily backups and 4 weekly backups.
- Keep backup restore access limited to authorized operators.
- Treat backup files as sensitive production data.

Backup command template:

```bash
APP_ENV=production \
BACKUP_ENCRYPTION=age \
bash scripts/postgres_backup.sh
```

## Restore Verification

Restore verification must use a disposable non-production database. It must
prove at least:

- required tables restore;
- Local Quiz Catalog tables, active catalog rows and import history restore;
- payment idempotency constraints restore;
- duplicate provider payment credit is not present;
- duplicate subscription credit for one payment is not present;
- active mistakes are not duplicated;
- progress counters are internally consistent.

Restore verification command template:

```bash
RESTORE_CONFIRM_NON_PRODUCTION=I_UNDERSTAND_THIS_IS_NOT_PRODUCTION \
bash scripts/postgres_restore_verify.sh
```

## Rollback Plan

Rollback is considered when bot availability, Telegram update processing,
answer writes, progress integrity, payment crediting, subscription state,
Local Catalog availability, admin protection or secret-safe logging is broken.

Before rollback:

- identify current version and previous known good version;
- identify migration and data impact;
- identify current and previous `ACTIVE_CATALOG_ID`;
- confirm rollback does not duplicate payment credit;
- confirm rollback does not delete learning state or corrupt daily limits;
- preserve incident evidence and logs without exposing secrets.

Rollback execution:

- stop the rollout or hold the current service state;
- rollback catalog by restoring the previous `ACTIVE_CATALOG_ID` when the issue
  is catalog-specific;
- restore the previous immutable image or Compose service definition;
- apply only approved migration rollback or forward-fix steps;
- do not restore production data unless incident response explicitly requires it;
- run post-rollback smoke checks.

Post-rollback verification:

- bot responds;
- existing users can continue;
- active Local Quiz Catalog selection works;
- answers save correctly;
- progress and mistakes remain linked;
- payment idempotency still holds;
- subscriptions remain accurate;
- monitoring shows recovery.

## Secret Rotation Procedure

Secret rotation is a separate controlled task. Do not rotate stable runtime
secrets during deploy proof unless an incident or explicit operator approval
requires it.

Rotation scope can include `BOT_TOKEN`, database and Redis URLs, backup
credentials, admin allowlists and payment configuration. Secret values must
never be printed, committed, pasted into logs or included in screenshots.

Before rotation:

- identify the exact secret, owner and dependent service;
- confirm rollback path and previous known-good runtime version;
- confirm the smoke checks to run after restart;
- schedule a maintenance window if the secret affects live Telegram delivery.

Rotation execution:

- write the new value only into protected runtime secret storage;
- restart only the services that read the changed secret;
- do not restart DB or Redis unless their own credentials changed;
- run health, Telegram and Local Catalog smoke checks without printing env values;
- revoke the old value only after the new runtime passes smoke checks.

Post-rotation verification:

- bot responds;
- Telegram `getMe` succeeds;
- `/start` and a safe training question work;
- Local Catalog smoke succeeds;
- logs contain no old or new secret values;
- monitoring shows no sustained error spike.

## Incident Response

1. Confirm the incident and assign severity.
2. Stop active damage.
3. Preserve evidence without printing secrets.
4. Identify affected area: bot, API, payment, data, admin, backup or logs.
5. Apply mitigation or rollback.
6. Verify recovery with smoke checks and monitoring.
7. Document timeline, impact, root cause and follow-up.
8. If secrets or user data are involved, rotate affected secrets, restrict
   access, check logs and backups for exposure, and document data impact.
