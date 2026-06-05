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
| `scripts/ops_smoke.sh` | Non-mutating health, Telegram and Quiz Bank smoke checks. |
| `scripts/quiz_bank_live_smoke.py` | Read-only Quiz Bank health, levels, themes, availability and question smoke checks. |
| `scripts/isolated_runtime_smoke.sh` | Non-mutating Docker smoke checks for isolated polling runtime. |
| `scripts/live_integration_gates.sh` | Manual staging gates for PostgreSQL, Redis, app health, Telegram, Quiz Bank and Telegram Stars evidence. |
| `scripts/payment_sandbox_evidence_check.py` | Non-secret Telegram Stars sandbox evidence validator. |
| `scripts/git_release_preflight.sh` | Non-mutating git provenance checks before push/release. |
| `scripts/postgres_backup.sh` | PostgreSQL dump with required production encryption. |
| `scripts/postgres_restore_verify.sh` | Disposable restore verification with schema and integrity checks. |
| `docs/21_isolated_server_deploy_inventory.md` | Active isolated server inventory and scoped deploy procedure. |

## Pre-Deploy Checklist

- Release version and immutable `BOT_IMAGE` are identified.
- `docker-compose.production.yml` renders successfully in the target env.
- Runtime env values are loaded from protected storage, not from committed files.
- `APP_ENV=production`, webhook mode is enabled and polling is disabled.
- `TELEGRAM_STARS_MODE=prod` is configured for production.
- `SECURITY_STATE_BACKEND=redis` is configured outside development.
- PostgreSQL and Redis are reachable from the bot runtime.
- Quiz Bank protected access is available for the selected environment.
- Admin allowlist is configured.
- Monitoring targets are configured for bot health, Caddy, DB, Redis, Quiz Bank,
  payments, subscriptions, admin auth failures, logs and backups.
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
token, Quiz Bank credentials, smoke base URL and `TELEGRAM_STARS_EVIDENCE_JSON`.
The Telegram Stars evidence JSON must contain only non-secret test facts and is
validated by `scripts/payment_sandbox_evidence_check.py`.

## Runtime Mode Gate

The default production runtime remains HTTPS webhook with Caddy. Polling is
acceptable only as an explicitly approved isolated runtime exception.

Webhook closure requires:

- `BOT_WEBHOOK_ENABLED=true` and `BOT_POLLING_ENABLED=false`;
- HTTPS `TELEGRAM_WEBHOOK_URL` and `TELEGRAM_WEBHOOK_SECRET` in protected env;
- Telegram webhook registration evidence;
- `scripts/ops_preflight.sh` and `scripts/ops_smoke.sh` passing in the target
  environment.

Polling exception closure requires:

- explicit operator approval naming polling as the active runtime mode;
- exactly one active bot process for the Telegram token;
- webhook disabled for that bot token before polling starts;
- isolated PostgreSQL and Redis confirmed running;
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
  isolated DB schema, Redis ping, required Quiz Bank env presence and recent
  bot logs checks.
- Manual Telegram flow passed:
  `/start -> menu -> quiz -> question -> answer -> result`.
- Quiz Bank connectivity passed through the bot runtime using the protected
  consumer env; secret values were not printed.

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
- Start or update services through Docker Compose.
- Watch bot, Caddy, DB and Redis health checks during rollout.
- Do not register or change a production Telegram webhook without explicit
  operator approval.

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
- Telegram `getMe` succeeds with the environment bot token.
- Telegram webhook delivery is confirmed by external deployment evidence.
- Quiz Bank `/v1/health` or approved smoke endpoint succeeds.
- `/start` works in Telegram.
- Level, theme and training start work with safe smoke data.
- Answer save, progress update and mistake creation work.
- Payment flow does not expose secrets; real payment credit is only verified in
  approved Telegram test or production mode.
- Admin metrics load only for an authorized admin.
- Logs, analytics and smoke output contain no secrets.
- Monitoring shows bot, DB, Redis, Quiz Bank, payment and backup health.

Smoke command template:

```bash
SMOKE_BASE_URL=https://<deployment-domain-managed-outside-repo> \
RUN_TELEGRAM_SMOKE=1 \
RUN_QUIZ_BANK_SMOKE=1 \
bash scripts/ops_smoke.sh
```

Live integration gate template:

```bash
RUN_TELEGRAM_SMOKE=1 \
RUN_QUIZ_BANK_SMOKE=1 \
QUIZ_BANK_SMOKE_LEVELS=A1,A2,B1 \
TELEGRAM_STARS_EVIDENCE_FILE=qa_evidence/telegram_stars_sandbox.json \
bash scripts/live_integration_gates.sh
```

When `RUN_QUIZ_BANK_SMOKE=1`, `scripts/live_integration_gates.sh` runs both the
basic smoke and `scripts/quiz_bank_live_smoke.py`. The live Quiz Bank smoke
checks `/v1/health`, `/v1/levels`, available themes, availability and one
question fetch per configured level without printing protected headers or
question payloads.

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
Quiz Bank integration, admin protection or secret-safe logging is broken.

Before rollback:

- identify current version and previous known good version;
- identify migration and data impact;
- confirm rollback does not duplicate payment credit;
- confirm rollback does not delete learning state or corrupt daily limits;
- preserve incident evidence and logs without exposing secrets.

Rollback execution:

- stop the rollout or hold the current service state;
- restore the previous immutable image or Compose service definition;
- apply only approved migration rollback or forward-fix steps;
- do not restore production data unless incident response explicitly requires it;
- run post-rollback smoke checks.

Post-rollback verification:

- bot responds;
- existing users can continue;
- answers save correctly;
- progress and mistakes remain linked;
- payment idempotency still holds;
- subscriptions remain accurate;
- monitoring shows recovery.

## Secret Rotation Procedure

Secret rotation is a separate controlled task. Do not rotate stable runtime
secrets during deploy proof unless an incident or explicit operator approval
requires it.

Rotation scope can include `BOT_TOKEN`, Quiz Bank keys, database and Redis URLs,
backup credentials, admin allowlists and payment configuration. Secret values
must never be printed, committed, pasted into logs or included in screenshots.

Before rotation:

- identify the exact secret, owner and dependent service;
- confirm rollback path and previous known-good runtime version;
- confirm the smoke checks to run after restart;
- schedule a maintenance window if the secret affects live Telegram delivery.

Rotation execution:

- write the new value only into protected runtime secret storage;
- restart only the services that read the changed secret;
- do not restart DB or Redis unless their own credentials changed;
- run health, Telegram and Quiz Bank smoke checks without printing env values;
- revoke the old value only after the new runtime passes smoke checks.

Post-rotation verification:

- bot responds;
- Telegram `getMe` succeeds;
- `/start` and a safe training question work;
- Quiz Bank smoke succeeds;
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
