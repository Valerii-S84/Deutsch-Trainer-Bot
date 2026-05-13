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
| Deployment model | Hetzner VPS + Docker Compose + Caddy + HTTPS webhook | Дає repeatable прод deployment із контролем TLS, reverse proxy та webhook endpoint | Підтримується production модель з окремими env, секретами й керованою інфраструктурою | Closed |
| Quiz Bank API integration | Бот — consumer-клієнт захищеного existing Quiz Bank API; quiz bank не дублюється локально | Вимагає збереження canonical source, унеможливлює drift контенту | Інтеграція через HTTP client, auth headers і contract-aware flows, без локального дублювання питань | Closed |
| Payments architecture | Telegram Stars, плани Free / Plus / Pro; тарифи й тривалості залишаються конфігураційними | Продуктово-зобов’язана платежна модель без hardcode-параметрів | Реалізується idempotent payment credit з валідацією user/plan/amount перед активацією | Closed |
| Admin model | Owner-only Telegram admin commands; метрики/звіти через БД та events | Знаходиться в межах продуктового і security контексту без зайвого обтяження UI | Адмін-дії доступні лише авторизованим власникам; web panel не запускається на цьому етапі | Closed |
| Analytics | Власна модель `analytics_events` у PostgreSQL | Потрібно мати append-only історію activation/learning/monetization/ops метрик | Відстеження подій: onboarding, quiz_started, quiz_answered, session_completed, subscription_viewed, payment_started, payment_completed | Closed |
| Security model | Secrets only via env/secrets; webhook secret; no secrets in logs; API keys protected; rate limits; payment audit log | Вимога security першого порядку для Telegram і платіжних сценаріїв | Безпекові контрзаходи вбудовуються в ядро ще до Milestone 1 | Closed |
| QA model | pytest + unit / integration / Telegram flow / Quiz Bank API integration / payment+subscription+progress regression | Мінімальний стандарт QA для production readiness | План тестування та критичні gates закладаються до розробки й перевіряються під час реалізації | Closed |
| Operations model | Dockerized production, backup, restore test, structured logs, monitoring, rollback plan, production smoke tests | Необхідно для операційної стійкості з контрольованими змінами | Умови для безпечного rollout і recovery стають частиною milestone 12 | Closed |

## 3. Still Open but Not Blocking Foundation

Наступні рішення залишаються відкритими до моменту payment implementation, але не блокують Milestone 1–3 за умови, що вони повністю винесені в config:

- exact Plus price (Decision Required Before Payment Implementation)
- exact Pro price (Decision Required Before Payment Implementation)
- Plus duration (Decision Required Before Payment Implementation)
- Pro duration (Decision Required Before Payment Implementation)
- final Telegram Stars package values (Decision Required Before Payment Implementation)
- final public tariff copy (Decision Required Before Payment Implementation)

Ці значення не hardcode-яться в коді чи документації налаштувань і підтягуються через конфігурацію.

## 4. Blocking Decisions Closed

Поточний стан у рамках milestone-locked prerequisites:

- stack
- framework
- DB
- deployment model
- API integration model
- payment architecture
- security model
- QA model

Усі вони закриті для старту подальшої імплементації.

## 5. Constraints

- no MVP wording
- no reduced scope
- no hardcoded secrets
- no hardcoded prices
- no unauthenticated Quiz Bank API access
- no production deploy without backup/restore/rollback plan

## 6. Milestone Unlock Result

- Milestone 1 can start.
- Milestone 2 can start after DB schema planning and migration design.
- Payment milestone still requires exact tariff values before final implementation, while respecting event/payment model and idempotency rules.
