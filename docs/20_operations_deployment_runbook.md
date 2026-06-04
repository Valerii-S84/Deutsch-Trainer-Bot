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
| `scripts/postgres_backup.sh` | PostgreSQL dump with required production encryption. |
| `scripts/postgres_restore_verify.sh` | Disposable restore verification with schema and integrity checks. |

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
