# Isolated Server Deploy Inventory

This document is the source of truth for the active isolated
`deutsch-trainer-bot` server runtime. It exists to prevent confusing this bot
with adjacent production services on the same host.

It does not approve a deploy by itself. Any command that changes server state
still requires explicit operator confirmation.

## Server Identity

The live SSH endpoint is restricted deployment inventory. Do not commit the
real host, IP address, domain, username, private key path or bot token here.

Before opening the server, load the target from protected inventory into the
operator shell:

```bash
export DEUTSCH_TRAINER_SSH_TARGET="<protected-inventory-ssh-target>"
ssh "$DEUTSCH_TRAINER_SSH_TARGET"
```

After login, verify the host identity against protected inventory before
running any command. If the target does not match the protected inventory,
stop.

## Application Paths

Only this path is in scope for this project:

```text
/opt/deutsch-trainer-bot
```

Current layout:

```text
/opt/deutsch-trainer-bot/current -> /opt/deutsch-trainer-bot/releases/<release>
/opt/deutsch-trainer-bot/releases/<release>
/opt/deutsch-trainer-bot/shared/runtime.env
/opt/deutsch-trainer-bot/backups
```

`/opt/deutsch-trainer-bot/shared/runtime.env` is protected runtime secret
storage. Do not print, copy into chat, commit, diff or paste its contents.

Open the active release on the server:

```bash
ssh "$DEUTSCH_TRAINER_SSH_TARGET"
cd /opt/deutsch-trainer-bot/current
pwd
readlink -f .
```

The live bot username and Telegram token ownership live in protected inventory.
No production HTTPS domain or webhook URL is committed for this isolated
runtime.

## Docker Scope

The Compose project name is:

```text
deutsch-trainer-bot
```

The only containers in scope are:

```text
deutsch-trainer-bot-bot-1
deutsch-trainer-bot-db-1
deutsch-trainer-bot-redis-1
```

Read-only scoped container check:

```bash
ssh "$DEUTSCH_TRAINER_SSH_TARGET" '
  docker ps --filter "name=deutsch-trainer-bot" \
    --format "{{.Names}}\t{{.Image}}\t{{.Status}}"
'
```

Runtime Compose file:

```text
/opt/deutsch-trainer-bot/current/docker-compose.isolated.yml
```

The isolated server currently uses deploy-only files that are present on the
server release but not in the GitHub application tree:

```text
Dockerfile.isolated
docker-compose.isolated.yml
```

Until those files are tracked in the repo, every new release must copy them
from the previous active release and update only the image tag inside the new
release directory.

## GitHub Comparison

GitHub source of truth:

```text
Valerii-S84/Deutsch-Trainer-Bot main
```

Local expected commit:

```bash
git fetch --prune origin
git rev-parse origin/main
```

Server release check:

```bash
ssh "$DEUTSCH_TRAINER_SSH_TARGET" '
  set -eu
  readlink -f /opt/deutsch-trainer-bot/current
  docker inspect --format "{{.Config.Image}}" deutsch-trainer-bot-bot-1
'
```

The release directory and bot image tag should match the short GitHub commit
that was intentionally deployed.

Pre-sync audit result recorded on 2026-06-04:

```text
GitHub main: d9302e4cc78c115ed90a0697badd8ce75a41cb13
Server current: /opt/deutsch-trainer-bot/releases/ec20844
Server bot image: deutsch-trainer-bot:ec20844
Status: server is behind GitHub main
```

## Forbidden Commands

Do not run these for this project unless a separate incident procedure
explicitly approves them:

```bash
docker compose down
docker compose up -d
docker restart $(docker ps -q)
docker stop $(docker ps -q)
docker system prune
cat /opt/deutsch-trainer-bot/shared/runtime.env
printenv
env
```

Do not inspect or modify adjacent paths under `/opt` while working on this bot.

## Blocking Gates

These gates must pass before any deploy command mutates the server.

### Release Gates

Run the local release checks against the exact GitHub `main` commit before
archiving it:

```bash
git fetch --prune origin
git switch main
git merge --ff-only origin/main
test -z "$(git status --porcelain)"

. .venv/bin/activate
bash scripts/local_ci.sh
python3 scripts/qa_release_gates.py --environment local \
  --known-risk "Local QA gates do not prove live Telegram Stars, target monitoring, target backup/restore, or production smoke evidence."
python3 scripts/secret_scan.py

EXPECTED_SHA="$(git rev-parse origin/main)"
SHORT_SHA="$(git rev-parse --short origin/main)"
```

The GitHub Actions `CI / test` check for `EXPECTED_SHA` must be successful.
Do not use this deploy procedure to bypass a skipped, missing or failing PR
gate. If deploying from a release branch before merge, run
`bash scripts/git_release_preflight.sh` on that branch before publishing it.

### Database Gates

The migration command changes the target database. Do not run it until all of
these are true:

- a recent encrypted backup exists or a new encrypted backup was created;
- restore verification passed on a disposable non-production database;
- migration impact was reviewed for the target commit;
- rollback or forward-fix steps are known if a migration is not safely
  backward compatible;
- DB and Redis containers are confirmed to belong to the
  `deutsch-trainer-bot` Compose project.

If the target commit changes `alembic/versions/`, `app/db/` or payment-credit
logic, treat the database gates as mandatory release blockers.

### Polling Runtime Gate

The isolated runtime uses polling by operator exception. Before recreating the
bot container, prove the polling gate without exposing tokens:

```bash
ssh "$DEUTSCH_TRAINER_SSH_TARGET" '
  set -eu
  running_count="$(docker ps \
    --filter "name=^/deutsch-trainer-bot-bot-1$" \
    --filter "status=running" \
    -q | wc -l | tr -d " ")"
  test "$running_count" = "1"

  docker inspect --format \
    "project={{index .Config.Labels \"com.docker.compose.project\"}} service={{index .Config.Labels \"com.docker.compose.service\"}}" \
    deutsch-trainer-bot-bot-1

  docker exec -i deutsch-trainer-bot-bot-1 python - <<'PY'
from __future__ import annotations

import json
import os
from urllib.request import urlopen

token = os.environ.get("BOT_TOKEN")
if not token:
    raise SystemExit("BOT_TOKEN is missing")

with urlopen(f"https://api.telegram.org/bot{token}/getWebhookInfo", timeout=10) as response:
    payload = json.loads(response.read().decode("utf-8"))

result = payload.get("result") or {}
webhook_url = result.get("url") or ""
print(f"telegram_webhook_disabled={'yes' if not webhook_url else 'no'}")
if webhook_url:
    raise SystemExit("Telegram webhook is configured; polling deploy is blocked")
PY
'
```

The protected Telegram token ownership inventory must also confirm that no
adjacent stack uses the same token. This procedure must not scan, stop or
restart adjacent production stacks to prove that fact.

## Deploy Sync Procedure

Run these commands only after explicit operator confirmation and all blocking
gates above.

Upload the GitHub main tree into a new isolated release directory:

```bash
git archive --format=tar "$EXPECTED_SHA" | ssh "$DEUTSCH_TRAINER_SSH_TARGET" "
  set -eu
  release=/opt/deutsch-trainer-bot/releases/$SHORT_SHA
  test ! -e \"\$release\"
  install -d \"\$release\"
  tar -x -C \"\$release\"
"
```

Copy server-only deploy files from the previous active release:

```bash
ssh "$DEUTSCH_TRAINER_SSH_TARGET" "
  set -eu
  old=\$(readlink -f /opt/deutsch-trainer-bot/current)
  release=/opt/deutsch-trainer-bot/releases/$SHORT_SHA
  cp \"\$old/Dockerfile.isolated\" \"\$release/Dockerfile.isolated\"
  cp \"\$old/docker-compose.isolated.yml\" \"\$release/docker-compose.isolated.yml\"
  python3 - \"\$release/docker-compose.isolated.yml\" \"$SHORT_SHA\" <<'PY'
from __future__ import annotations

import re
import sys
from pathlib import Path

path = Path(sys.argv[1])
short_sha = sys.argv[2]
content = path.read_text(encoding='utf-8')
content = re.sub(
    r'image: deutsch-trainer-bot:[A-Za-z0-9._-]+',
    f'image: deutsch-trainer-bot:{short_sha}',
    content,
)
path.write_text(content, encoding='utf-8')
PY
"
```

Build the new bot image without touching running containers:

```bash
ssh "$DEUTSCH_TRAINER_SSH_TARGET" "
  set -eu
  release=/opt/deutsch-trainer-bot/releases/$SHORT_SHA
  docker build \
    -f \"\$release/Dockerfile.isolated\" \
    -t \"deutsch-trainer-bot:$SHORT_SHA\" \
    \"\$release\"
"
```

Apply migrations through a one-off scoped container only after the database
gates passed:

```bash
ssh "$DEUTSCH_TRAINER_SSH_TARGET" "
  set -eu
  release=/opt/deutsch-trainer-bot/releases/$SHORT_SHA
  docker compose \
    -p deutsch-trainer-bot \
    -f \"\$release/docker-compose.isolated.yml\" \
    --profile tools \
    run --rm --no-deps migrate
"
```

Switch the active release and recreate only the bot container after the polling
runtime gate passed:

```bash
ssh "$DEUTSCH_TRAINER_SSH_TARGET" "
  set -eu
  release=/opt/deutsch-trainer-bot/releases/$SHORT_SHA
  ln -sfn \"\$release\" /opt/deutsch-trainer-bot/current
  docker compose \
    -p deutsch-trainer-bot \
    -f /opt/deutsch-trainer-bot/current/docker-compose.isolated.yml \
    up -d --no-deps bot
"
```

Post-deploy read-only verification:

```bash
ssh "$DEUTSCH_TRAINER_SSH_TARGET" "
  set -eu
  readlink -f /opt/deutsch-trainer-bot/current
  docker ps --filter 'name=deutsch-trainer-bot' \
    --format '{{.Names}}\t{{.Image}}\t{{.Status}}'
  RUN_TELEGRAM_SMOKE=1 \
    bash /opt/deutsch-trainer-bot/current/scripts/isolated_runtime_smoke.sh
"
```

## Rollback

Rollback must target a known previous release directory under
`/opt/deutsch-trainer-bot/releases`.

Database rollback is not implied by switching the bot release. If migrations
ran during the failed deploy, use the migration rollback or forward-fix plan
approved in the database gates.

```bash
ssh "$DEUTSCH_TRAINER_SSH_TARGET" "
  set -eu
  rollback=/opt/deutsch-trainer-bot/releases/<previous-release>
  test -d \"\$rollback\"
  ln -sfn \"\$rollback\" /opt/deutsch-trainer-bot/current
  docker compose \
    -p deutsch-trainer-bot \
    -f /opt/deutsch-trainer-bot/current/docker-compose.isolated.yml \
    up -d --no-deps bot
"
```

After rollback, rerun the same scoped verification commands. Do not restart DB
or Redis unless a separate DB/Redis incident procedure explicitly requires it.
