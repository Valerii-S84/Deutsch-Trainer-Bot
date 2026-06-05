# 🇩🇪🤖 Deutsch Trainer Bot

**Deutsch Trainer Bot** — це production-oriented Telegram bot для тренування
німецької мови через короткі quiz-сесії, прогрес, повторення помилок,
платні плани Free / Plus / Pro та інтеграцію із зовнішнім Quiz Bank API.

Проєкт не зберігає власний банк питань у репозиторії. Bot працює як
захищений consumer-клієнт Quiz Bank API, зберігаючи у своїй базі лише
користувачів, сесії, відповіді, прогрес, помилки, підписки, payments,
analytics events і operational evidence.

> ✅ Основний принцип: **секрети, production hostnames, токени, ключі,
> database URLs і protected inventory не комітяться в repo**.

---

## 🧭 Що це за продукт

Deutsch Trainer Bot допомагає користувачу тренувати німецьку мову в Telegram:

- 🟢 обрати рівень;
- 🧩 обрати тему;
- ❓ отримувати питання з Quiz Bank API;
- ✅ відповідати через Telegram UI;
- 📈 бачити прогрес;
- 🔁 повертатися до помилок;
- ⭐ користуватися Free / Plus / Pro entitlements;
- 💳 проходити Telegram Stars payment flow;
- 🛡️ працювати з rate limits, duplicate update guard і безпечними runtime
  налаштуваннями.

Усі user-facing bot messages мають бути **німецькою мовою**. README і
операційна документація можуть бути українською або англійською, але тексти,
які бачить користувач у Telegram, мають лишатися German-only.

---

## ✅ Поточний статус

Стан на поточний `main`:

- ✅ repository foundation реалізований;
- ✅ bot runtime, handlers, keyboards і routers присутні;
- ✅ PostgreSQL schema і SQLAlchemy repositories реалізовані;
- ✅ Quiz Bank API client/service/schema layer реалізовані;
- ✅ progress, mistakes, subscriptions, payments, analytics і admin metrics
  покриті тестами;
- ✅ local CI і GitHub Actions CI налаштовані;
- ✅ isolated server runtime задокументований;
- ⚠️ isolated server runtime state не є статичним repo-фактом:
  перед deploy або audit його потрібно звіряти через protected inventory і
  [`docs/21_isolated_server_deploy_inventory.md`](docs/21_isolated_server_deploy_inventory.md);
- ⚠️ full production closure ще потребує external evidence gates:
  monitoring, target backup/restore, Telegram Stars live evidence,
  webhook/prod-mode closure або approved isolated polling mode evidence.

Детальний production readiness status живе тут:

- [`docs/14_implementation_roadmap.md`](docs/14_implementation_roadmap.md)
- [`docs/15_roadmap_execution_log.md`](docs/15_roadmap_execution_log.md)
- [`docs/20_operations_deployment_runbook.md`](docs/20_operations_deployment_runbook.md)
- [`docs/21_isolated_server_deploy_inventory.md`](docs/21_isolated_server_deploy_inventory.md)

---

## 🧱 Tech Stack

| Area | Technology |
|---|---|
| Language | Python 3.12+ |
| Telegram framework | aiogram 3.x |
| Runtime modes | Local polling, production webhook, approved isolated polling exception |
| HTTP / API client | httpx |
| Database | PostgreSQL |
| ORM / migrations | SQLAlchemy 2.x async + Alembic |
| Cache / locks / rate limits | Redis |
| Config | Pydantic Settings |
| Payments | Telegram Stars |
| Tests | pytest, pytest-asyncio |
| Deployment direction | Docker Compose + Caddy + protected runtime env |

---

## 🧩 Основні можливості

### 🤖 Telegram bot runtime

- aiogram dispatcher;
- modular routers;
- handlers для start/menu/level/theme/training/profile/review/subscription;
- German-only UI copy checks;
- callback-safe flow;
- duplicate Telegram update guard;
- structured logging with redaction.

### 📚 Quiz Bank API integration

- protected API client;
- levels/themes/questions/lookup flows;
- schema validation;
- retries/timeouts;
- unavailable content handling;
- no local duplication of canonical question bank.

### 🧠 Training flow

- training session lifecycle;
- answer handling;
- progress update;
- mistake creation;
- daily limits;
- integration with entitlements.

### 📈 Progress model

- topic progress;
- accuracy;
- coverage;
- stability;
- weakness;
- recency;
- recommendations.

### 🔁 Mistakes and review

- mistake creation;
- repeat flow;
- improved/resolved/reopened states;
- Plus+ entitlement rules for repeat/review behavior.

### ⭐ Entitlements and subscriptions

- Free / Plus / Pro plans;
- daily limits;
- paid feature gates;
- pending/active/expired subscription states;
- renewal coverage.

### 💳 Telegram Stars payments

- Stars payload format;
- pre-checkout validation;
- successful payment credit;
- idempotent payment handling;
- provider reference reuse protection;
- subscription activation after credit.

Live Stars evidence is still a production readiness gate and must be handled
with explicit operator approval.

### 📊 Analytics and admin

- append-only analytics events;
- activation, training, payment, subscription and operational events;
- owner-only admin access model;
- admin metrics tests.

### 🛡️ Security controls

- secrets only through runtime environment / protected inventory;
- secret scan in local and CI gates;
- no secrets in logs/analytics;
- webhook secret support;
- Redis-backed rate limits and duplicate update guard outside development;
- owner-only admin actions.

---

## 🗂️ Repository Structure

```text
app/
  bot/                 Telegram handlers, keyboards, routers, middleware
  db/                  SQLAlchemy models, session setup, db types
  quiz_bank/           Quiz Bank API client, schemas and service
  repositories/        Database access layer
  security/            Rate limits and runtime security helpers
  services/            Product/business services
  main.py              Runtime entrypoint

alembic/
  versions/            Database migrations

deploy/
  *.template           Non-secret deploy templates

docs/
  01-21_*.md           Product, architecture, QA, operations and deploy docs

scripts/
  local_ci.sh          Local compile/test/security gate
  qa_release_gates.py  Release QA gate runner
  secret_scan.py       Tracked-file secret scan
  isolated_runtime_smoke.sh
  ops_preflight.sh
  ops_smoke.sh
  postgres_backup.sh
  postgres_restore_verify.sh

tests/
  test_*.py            Unit, integration, security and release gate tests
```

---

## 🚀 Local Setup

### 1. Create virtual environment

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e ".[dev]"
```

### 2. Configure local environment

Use local/staging credentials only. Do not commit `.env`.

```bash
cp .env.example .env
```

Before running the bot, replace or remove every placeholder value copied from
`.env.example`. Placeholder values like `<request-timeout-seconds>` are not
valid runtime values and will make settings validation fail.

Safe local numeric defaults:

```text
BOT_MAX_REQUEST_TIMEOUT=30
QUIZ_BANK_TIMEOUT_SECONDS=3
QUIZ_BANK_MAX_RETRIES=2
```

Then fill only the secret or environment-specific values needed for your local
run:

- `BOT_TOKEN`
- `DATABASE_URL`
- `REDIS_URL`
- `QUIZ_BANK_API_BASE_URL`
- `QUIZ_BANK_EDGE_API_KEY`
- `QUIZ_BANK_CONSUMER_ID`
- `QUIZ_BANK_CONSUMER_API_KEY`
- `ADMIN_TELEGRAM_USER_IDS`

For local polling, use development-safe runtime mode:

```text
APP_ENV=development
BOT_POLLING_ENABLED=True
BOT_WEBHOOK_ENABLED=False
TELEGRAM_STARS_MODE=test
```

### 3. Run the bot locally

```bash
. .venv/bin/activate
python -m app.main
```

Runtime starts in polling mode for development unless webhook settings are
explicitly enabled for non-development environments.

---

## 🧪 Checks and QA

### Main local CI

```bash
. .venv/bin/activate
bash scripts/local_ci.sh
```

This runs:

- pip upgrade for audit tooling;
- Python compile checks;
- QA release gate plan validation;
- static policy check;
- tracked-file secret scan;
- dependency and Bandit security audit;
- structural file/function/class/parameter/nesting limits;
- pytest regression suite with coverage threshold.

### Full release QA gates

```bash
. .venv/bin/activate
python scripts/qa_release_gates.py --environment local \
  --known-risk "Local QA gates do not prove live Telegram Stars, target monitoring, target backup/restore, or production smoke evidence."
```

The release gate runner groups checks by product risk:

- coverage;
- dependency/security audit;
- Docker config/build;
- PostgreSQL migration/runtime schema;
- Redis runtime smoke;
- progress logic;
- answer -> progress -> mistake -> analytics flow;
- Telegram handlers and keyboards;
- Quiz Bank contract and failures;
- payments and subscriptions;
- security and abuse;
- German copy;
- release evidence.

Full release QA gates require Docker plus `DATABASE_URL` or `TEST_DATABASE_URL`
and `REDIS_URL`. GitHub CI provides PostgreSQL and Redis services for pull
requests and `main` pushes. Protected Telegram, Quiz Bank and Telegram Stars
checks run through the manual staging integration workflow because they require
secrets and external sandbox evidence.

### Secret scan

```bash
python scripts/secret_scan.py
```

Secret scan is intentionally strict about token-shaped values, private key
blocks, AWS-style keys and assigned secret patterns. If it fails, fix the
source before publishing anything.

---

## 🧬 Database and Migrations

Alembic controls schema changes:

```bash
alembic upgrade head
```

Runtime PostgreSQL verification:

```bash
bash scripts/db_runtime_check.sh
```

Schema-impacting work must include:

- SQLAlchemy model changes;
- Alembic migration;
- repository/service alignment;
- runtime PostgreSQL verification;
- rollback or forward-fix thinking for production.

Do not run destructive DB operations without explicit approval.

---

## 🔐 Secrets and Protected Data

Never commit or print:

- Telegram bot tokens;
- webhook secrets;
- Quiz Bank keys;
- database URLs with credentials;
- Redis URLs with credentials;
- Telegram Stars/payment secrets;
- backup credentials;
- SSH private keys;
- production hostnames or protected deployment inventory.

Allowed in the repo:

- env variable names;
- non-secret templates;
- placeholders;
- documentation that points to protected inventory without revealing it.

Protected runtime details live outside this repository.

---

## 🏗️ Deployment Model

The locked production direction is:

```text
Hetzner VPS + Docker Compose + Caddy + HTTPS webhook
```

The current server also has an approved isolated polling runtime procedure.
That path is documented here:

- [`docs/21_isolated_server_deploy_inventory.md`](docs/21_isolated_server_deploy_inventory.md)

Important boundaries:

- deploy commands require explicit operator confirmation;
- only `/opt/deutsch-trainer-bot` is in scope for this project;
- adjacent production services must not be inspected, restarted or modified;
- DB and Redis are not restarted during bot-only rollout;
- live SSH endpoint and host aliases stay in protected inventory;
- `runtime.env` must never be printed.

Post-deploy isolated smoke:

```bash
RUN_TELEGRAM_SMOKE=1 \
bash /opt/deutsch-trainer-bot/current/scripts/isolated_runtime_smoke.sh
```

Run this only on the approved target server and only within the scoped deploy
procedure.

---

## 🧾 Documentation Map

| Document | Purpose |
|---|---|
| [`docs/01_product_charter.md`](docs/01_product_charter.md) | Product charter |
| [`docs/02_requirements_srs.md`](docs/02_requirements_srs.md) | Requirements |
| [`docs/03_use_cases.md`](docs/03_use_cases.md) | User journeys and scenarios |
| [`docs/04_domain_model.md`](docs/04_domain_model.md) | Domain model |
| [`docs/05_progress_model.md`](docs/05_progress_model.md) | Progress and learning model |
| [`docs/06_ux_flows.md`](docs/06_ux_flows.md) | Telegram UX flows |
| [`docs/07_monetization_model.md`](docs/07_monetization_model.md) | Free / Plus / Pro and payments |
| [`docs/08_api_integration.md`](docs/08_api_integration.md) | Quiz Bank API integration standard |
| [`docs/09_data_standard.md`](docs/09_data_standard.md) | Data contracts |
| [`docs/10_analytics_metrics.md`](docs/10_analytics_metrics.md) | Analytics metrics |
| [`docs/11_security_privacy.md`](docs/11_security_privacy.md) | Security and privacy model |
| [`docs/12_quality_assurance.md`](docs/12_quality_assurance.md) | QA strategy |
| [`docs/13_operations.md`](docs/13_operations.md) | Operations standard |
| [`docs/14_implementation_roadmap.md`](docs/14_implementation_roadmap.md) | Implementation roadmap and readiness |
| [`docs/15_roadmap_execution_log.md`](docs/15_roadmap_execution_log.md) | Execution evidence log |
| [`docs/16_architecture_lock.md`](docs/16_architecture_lock.md) | Locked architecture decisions |
| [`docs/20_operations_deployment_runbook.md`](docs/20_operations_deployment_runbook.md) | Deployment runbook |
| [`docs/21_isolated_server_deploy_inventory.md`](docs/21_isolated_server_deploy_inventory.md) | Scoped isolated server inventory |

---

## 🌿 Git Workflow

Project rules:

- work on feature branches;
- do not push directly to `main`;
- use Conventional Commits;
- open PRs for review;
- keep PR scope narrow;
- describe checks and unresolved risks.

Examples:

```bash
git switch -c docs/update-readme
git status -sb
git add README.md
git commit -m "docs: add project readme"
git push -u origin docs/update-readme
```

---

## ✅ Definition of Done

For normal repository work, a change is done only when:

- scope is narrow and explicit;
- unrelated files are untouched;
- no secrets are introduced;
- relevant tests/checks pass;
- risks are documented instead of hidden;
- PR describes scope, files, checks and open questions.

For deploy work, done additionally requires:

- GitHub `main` and local `main` are synchronized;
- release gates pass;
- target server path is verified from protected inventory;
- only scoped containers are touched;
- post-deploy smoke passes;
- DB/Redis are not restarted unless explicitly approved.

---

## 🧠 Human Notes

This repository is intentionally strict because the bot touches real user
learning state, payments, protected Quiz Bank access and production runtime
credentials. The process may feel heavier than a small demo bot, but it keeps
the important line clear:

**code and docs are public-reviewable; secrets and production inventory are not.**
