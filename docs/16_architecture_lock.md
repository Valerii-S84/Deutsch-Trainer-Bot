# 16. Architecture Lock

## 1. Purpose

Цей документ фіксує production-рішення, які блокують або розблоковують перехід від roadmap до реалізації коду.  
Він використовується як контрольний артикул для старту Milestone 1 без змін продуктового змісту або скорочення функціональності.

## 2. Locked Decisions

| Area | Locked Decision | Reason | Impact | Status |
|---|---|---|---|---|
| Implementation stack | Python 3.12+ | Вибраний через стабільну екосистему, сильну підтримку асинхронності та доступність production-ready tooling | Базові компоненти фіксуються для всього backend коду, CI та інфраструктури | Closed |
| Telegram framework | aiogram 3.x | Працює з Telegram Bot API, callback-и, інлайн-кнопками, підтримкою payments flow в практиці проєктів | Створюється ядро бота на aiogram, включно з safe callback handling та fallback станами | Closed |
| Database | PostgreSQL | Рекомендовано для транзакційної цілісності, індексів, JSON-метаданих та backup-механізмів | Модель даних буде реляційною з чіткими foreign keys, constraint-ами й audit-треками | Closed |
| ORM / migrations | SQLAlchemy 2.x async + Alembic | Забезпечує async-клієнт та контроль міграцій зі зворотною сумісністю | Уніфікований data layer для сервісів, тестів та transaction boundaries | Closed |
| Redis usage | Використовувати для rate limits, locks, кешу або коротких runtime станів | Не дублює durable state, потрібен для операційних запобіжників і продуктивності | Redis застосовується як допоміжний компонент, не як primary persistent store | Closed |
| Deployment model | Hetzner VPS + Docker Compose + Caddy + HTTPS webhook | Дає repeatable prod deployment із контролем TLS, reverse proxy та webhook endpoint | Підтримується production модель з окремими env, секретами й керованою інфраструктурою | Closed |
| Production webhook endpoint | Exact FQDN не комітиться; production inventory задає `TELEGRAM_WEBHOOK_URL=https://<production-domain>`, path locked as `/telegram/webhook`, resulting URL is `<TELEGRAM_WEBHOOK_URL><TELEGRAM_WEBHOOK_PATH>` | Не розкриває production hostname у repo і зберігає repeatable config contract | `BOT_WEBHOOK_ENABLED=true`, HTTPS і `TELEGRAM_WEBHOOK_SECRET` обов'язкові в production | Closed |
| Quiz Bank API integration | Бот — consumer-клієнт захищеного existing Quiz Bank API; quiz bank не дублюється локально | Вимагає збереження canonical source, унеможливлює drift контенту | Інтеграція через HTTP client, auth headers і contract-aware flows, без локального дублювання питань | Closed |
| Payments architecture | Telegram Stars, плани Free / Plus / Pro; Release 1 launch config locked below and remains env-overridable through typed config | Продуктово-зобов'язана платежна модель без секретів у коді | Реалізується idempotent payment credit з валідацією user/currency/amount/provider reference перед активацією | Closed |
| Admin model | Owner-only Telegram admin commands; метрики/звіти через БД та events | Знаходиться в межах продуктового і security контексту без зайвого обтяження UI | Адмін-дії доступні лише авторизованим власникам; web panel не запускається на цьому етапі | Closed |
| Analytics | Власна модель `analytics_events` у PostgreSQL | Потрібно мати append-only історію activation/learning/monetization/ops метрик | Відстеження подій: onboarding, quiz_started, quiz_answered, session_completed, subscription_viewed, payment_started, payment_completed | Closed |
| Security model | Secrets only via env/secrets; webhook secret; no secrets in logs/analytics; API keys protected; Redis-backed global rate limits and duplicate update guard outside development; payment audit log | Вимога security першого порядку для Telegram і платіжних сценаріїв | Безпекові контрзаходи вбудовуються в ядро і валідовані config/tests | Closed |
| QA model | pytest + unit / integration / Telegram flow / Quiz Bank API integration / payment+subscription+progress regression | Мінімальний стандарт QA для production readiness | План тестування та критичні gates закладаються до розробки й перевіряються під час реалізації | Closed |
| Secret storage and rotation | Production secrets live outside repo in restricted VPS secret/env storage; local `.env` is gitignored; rotation is env-only and followed by process restart + smoke test | Не допускає секретів у code/docs/tests і дозволяє rotation без code change | Covers Telegram token, Quiz Bank keys, Stars mode/config, DB/Redis URLs, backup credentials and admin IDs | Closed |
| Monitoring stack | Release 1 uses Docker health, Caddy access/error logs, structured app logs with redaction, PostgreSQL admin metrics, DB/Redis health checks and external HTTPS uptime check | Достатньо для first production without adding an unapproved APM dependency | Alerts cover bot availability, API/payment errors, admin auth failures and backup freshness | Closed |
| Backup policy | Encrypted PostgreSQL backup before production launch, before payment/data migrations, and daily after launch; minimum retention 7 daily + 4 weekly; restore test before launch and monthly after launch | Payment/progress data must be recoverable and restore must not duplicate credits | Backup credentials are restricted secrets; restore evidence is required before production readiness | Closed |
| Release owner | Tech owner owns Release 1 closure gate; Product owner approves tariff/copy; Ops owner approves monitoring/backup/restore/deploy readiness | Production readiness needs accountable sign-off without changing product strategy | Release is blocked if any owner gate is missing evidence | Closed |
| Operations model | Dockerized production, backup, restore test, structured logs, monitoring, rollback plan, production smoke tests | Необхідно для операційної стійкості з контрольованими змінами | Умови для безпечного rollout і recovery стають частиною milestone 12 | Closed |

## 3. Release 1 Launch Configuration

Release 1 launch values are locked as typed runtime config defaults and remain env-overridable only through validated settings:

| Config | Release 1 value | Evidence |
|---|---:|---|
| `FREE_DAILY_QUESTION_LIMIT` | `5` questions/day | `app/config.py` validation: Free < Plus < Pro |
| `PLUS_DAILY_QUESTION_LIMIT` | `25` questions/day | service-layer daily limit enforcement |
| `PRO_DAILY_QUESTION_LIMIT` | `100` questions/day | service-layer daily limit enforcement |
| `PLUS_PRICE_STARS` | `100` Stars | Telegram Stars invoice config |
| `PRO_PRICE_STARS` | `250` Stars | Telegram Stars invoice config |
| `PLUS_DURATION_DAYS` | `30` days | credited subscription expiry calculation |
| `PRO_DURATION_DAYS` | `90` days | credited subscription expiry calculation |
| `TELEGRAM_STARS_MODE` | `test` by default, `prod` only by production env | typed validation |
| `PAYWALL_COOLDOWN_POLICY` | `none` | explicit Release 1 decision; no suppression logic is enabled |

Public tariff copy for Release 1:

```text
Plus
Mehr Übungen pro Tag.
Vollständiger Fortschritt.
Fehler gezielt wiederholen.
Tägliche Empfehlungen.

Pro
Mehr Übungen pro Tag.
Erweiterte Statistik.
Tieferer Fehlerüberblick.
Persönlicher Lernplan.
```

Monthly limits decision:

- Decision: not in Release 1.
- Enforcement surface for Release 1 is daily limits plus feature entitlements.
- Adding monthly limits later requires schema/service/test scope.

Cancel/refund decision for Telegram Stars:

- Decision: not supported in Release 1 bot runtime.
- Telegram Stars successful payment is credited idempotently; failed/cancelled internal states may be recorded, but provider-specific refund/cancel automation is not exposed.
- Any refund/cancel operation remains manual provider/operator procedure until a separate provider-specific milestone.

## 4. Still Open but Not Blocking Code Closure

Наступні рішення не блокують Milestone 0-11 code closure:

- Quiz Bank runtime consumer contract для levels/themes/availability/questions/lookup/metadata/error taxonomy реалізується в schemas/service/tests; фінальний OpenAPI freeze потрібен перед production release.
- Quiz Bank cache policy для Milestone 4–7: short-lived catalog/availability/metadata cache; повний локальний question bank заборонений.
- Free mistake repeat policy для поточної імплементації: повторення помилок є Plus+ entitlement; зміна на Free trial потребує окремого product decision.

## 5. Blocking Decisions Closed

Поточний стан у рамках milestone-locked prerequisites:

- stack
- framework
- DB
- deployment model
- API integration model
- Quiz Bank runtime consumer contract and cache scope for Milestone 4-7
- final Free/Plus/Pro daily limits
- monthly limits not in Release 1
- paywall cooldown policy `none`
- Plus+ mistake repeat entitlement for current review flow
- payment architecture, Stars payload format and idempotent credit rules
- approved Plus/Pro prices and durations
- security model
- Redis-backed global security state outside development
- QA model
- monitoring, backup, restore cadence and release owner

Усі вони закриті для старту та закриття Milestone 0-11. Production release still requires safe credentials, actual domain value in deploy inventory, Telegram Stars prod mode, backup/restore evidence and production smoke tests.

## 6. Telegram Stars Verification Contract

Release 1 payment payload format:

```text
dtbpay:{payment_id}:{idempotency_key}
```

Telegram Stars fields:

- currency: `XTR`
- provider token: empty string for Stars
- provider mode: `TELEGRAM_STARS_MODE=test|prod`
- amount: exact plan Stars amount from config
- provider references: Telegram charge id and provider charge id if present

Verification expectations:

1. payload parses to an existing payment id and idempotency key;
2. Telegram user owns the payment;
3. currency is `XTR`;
4. amount matches the stored plan config;
5. provider reference is not reused by another payment;
6. paid access opens only after `payment.status=credited` and active non-expired subscription exists.

Raw provider payloads are not logged, stored in analytics, or shown to users.

## 7. Constraints

- no MVP wording
- no reduced scope
- no hardcoded secrets
- no secret prices or credentials in code; approved public launch defaults live in typed config and can be overridden by env
- no unauthenticated Quiz Bank API access
- no production deploy without backup/restore/rollback plan

## 8. Milestone Unlock Result

- Milestone 0 can be re-closed with the Release 1 production decisions above.
- Milestone 8 can close when tests confirm Free/Plus/Pro limits, expired/pending subscription behavior and no data loss.
- Milestone 9 can close when tests confirm invoice/pre-checkout/successful payment/credit/idempotency/mismatch cases.
- Milestone 11 can close when Redis-backed rate limits, duplicate update guard, admin auth, redaction and secret scans pass.
