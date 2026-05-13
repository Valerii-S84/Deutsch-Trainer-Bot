# Deutsch Trainer Bot — API Integration

## 1. Document Purpose

Цей документ описує інтеграцію **Deutsch Trainer Bot** з **API Quiz Bank**.

Він фіксує:

* які endpoint-и потрібні боту;
* які дані бот отримує з API;
* які metadata потрібні для прогресу;
* як бот має обробляти помилки API;
* що робити, якщо API тимчасово недоступний;
* які інваріанти інтеграції не можна порушувати.

Документ не є OpenAPI-специфікацією, кодом клієнта або фінальним мережевим контрактом.

Його мета — задати строгий, перевірюваний і презентаційно зрозумілий інтеграційний стандарт, який можна перетворити на OpenAPI schema, API client, mocks, tests і production monitoring.

---

## 2. Modeling Standard

Інтеграція описана в строгому академічному форматі.

У межах цього документа **Stanford-level standard** означає:

* кожен endpoint має чітку відповідальність;
* кожен payload має визначені обов’язкові поля;
* кожне поле має навчальне або технічне обґрунтування;
* кожна помилка має deterministic handling rule;
* кожен fallback має межі застосування;
* кожен cache має TTL, scope і invalidation rule;
* кожна відповідь API вважається недовіреним input до валідації;
* кожне правило придатне для unit, integration або contract tests;
* жодне правило не дублює Quiz Bank всередині бота.

Головний принцип:

> API Quiz Bank володіє навчальним контентом. Deutsch Trainer Bot володіє навчальним станом користувача.

---

## 3. Integration Boundary

## 3.1. API Quiz Bank Responsibility

API Quiz Bank відповідає за:

* список доступних рівнів;
* список доступних тем;
* доступність питань по рівню й темі;
* навчальні питання;
* варіанти відповідей;
* правильну відповідь;
* пояснення;
* metadata для прогресу;
* версію контенту, якщо вона підтримується.

## 3.2. Bot Responsibility

Deutsch Trainer Bot відповідає за:

* Telegram user state;
* вибраний рівень і тему;
* тренувальні сесії;
* відповіді користувача;
* progress model;
* mistakes;
* recommendations;
* daily limits;
* subscriptions;
* analytics events;
* user-facing German copy;
* безпечну поведінку при API failure.

## 3.3. Ownership Rule

Canonical source of truth для питання — API Quiz Bank.

Бот може зберігати:

* `item_id`;
* `level`;
* `theme`;
* `content_version`, якщо доступний;
* `metadata_snapshot`;
* `correct_answer_snapshot` для історичного аудиту відповіді;
* `explanation_snapshot`, якщо вона показувалась користувачу;
* мінімальний `question_text_snapshot`, якщо потрібен для журналу помилок.

Бот не має зберігати повний банк питань як власну копію.

---

## 4. Required API Capabilities

Release 1 потребує таких API-можливостей:

1. Перевірити доступність Quiz Bank.
2. Отримати підтримувані рівні.
3. Отримати теми для рівня.
4. Отримати availability і кількість питань для level + theme.
5. Отримати batch питань для тренувальної сесії.
6. Отримати конкретне питання за `item_id`.
7. Отримати metadata, потрібні для progress model.

Точні URL можуть відрізнятися у фінальній OpenAPI-специфікації.

У цьому документі endpoint-и описані як рекомендований логічний контракт.

---

## 5. Endpoint Contract Overview

| Capability | Recommended Endpoint | Method | Required For |
|---|---|---|---|
| Health check | `/health` | `GET` | Readiness, monitoring, fallback decision. |
| Levels catalog | `/levels` | `GET` | Level selection, validation. |
| Themes catalog | `/levels/{level}/themes` | `GET` | Theme selection, availability. |
| Theme availability | `/availability` | `GET` | Progress coverage, recommendations, UX filtering. |
| Question batch | `/questions` | `GET` | Training session, mistake review, recommended session. |
| Question lookup | `/questions/{item_id}` | `GET` | Mistake review, historical item refresh. |
| Metadata catalog | `/metadata` | `GET` | Progress model validation, admin diagnostics. |

Інваріант:

```text
Question batch must be sufficient to run a training session,
but it must not become the bot's internal question bank.
```

---

## 6. Authentication and Transport

## 6.1. Authentication

API Quiz Bank має бути доступний тільки серверній частині бота.

Базові правила:

* API key не передається в Telegram;
* API key не зберігається в репозиторії;
* API key читається з environment або secret storage;
* ключі не логуються;
* response з API не має повертатися користувачу як raw payload.

## 6.2. Transport

Production traffic має використовувати HTTPS.

Кожен запит має мати:

* timeout;
* request id або correlation id;
* retry policy для safe reads;
* structured error handling;
* schema validation після отримання відповіді.

## 6.3. Required Headers

Рекомендовані headers:

| Header | Purpose |
|---|---|
| `Authorization` | Доступ до Quiz Bank API. |
| `X-Request-Id` | Кореляція логів між ботом і API. |
| `Accept` | Очікуваний формат відповіді. |
| `User-Agent` | Ідентифікація клієнта Deutsch Trainer Bot. |

Заборонено передавати в Quiz Bank зайві персональні дані Telegram-користувача, якщо вони не потрібні для формування питань.

---

## 7. Health Endpoint

## 7.1. Purpose

Health endpoint потрібен для:

* monitoring;
* startup diagnostics;
* admin status;
* circuit breaker decision;
* відділення повної недоступності API від помилки конкретного запиту.

## 7.2. Recommended Request

```text
GET /health
```

## 7.3. Required Response Fields

| Field | Type | Required | Purpose |
|---|---:|---:|---|
| `status` | string | Yes | `ok`, `degraded`, `unavailable`. |
| `service` | string | Yes | Назва сервісу. |
| `version` | string | No | Версія API або deployment. |
| `content_version` | string | No | Версія контенту. |
| `checked_at` | datetime | Yes | Час відповіді API. |

## 7.4. Handling Rule

| Status | Bot Behavior |
|---|---|
| `ok` | API може використовуватись нормально. |
| `degraded` | Бот може використовувати API, але має очікувати partial failures. |
| `unavailable` | Бот не стартує нові API-залежні сесії без fallback. |

Health endpoint не замінює обробку помилок на інших endpoint-ах.

---

## 8. Levels Endpoint

## 8.1. Purpose

Levels endpoint повертає підтримувані CEFR-рівні, які має показувати бот.

Release 1 підтримує:

```text
A1
A2
B1
B2
C1
```

## 8.2. Recommended Request

```text
GET /levels
```

## 8.3. Required Response Fields

| Field | Type | Required | Purpose |
|---|---:|---:|---|
| `levels` | array | Yes | Список рівнів. |
| `levels[].code` | string | Yes | `A1`, `A2`, `B1`, `B2`, `C1`. |
| `levels[].display_name` | string | Yes | Людська назва рівня. |
| `levels[].is_active` | boolean | Yes | Чи можна показувати рівень користувачу. |
| `content_version` | string | No | Версія каталогу. |

## 8.4. Validation Rule

Бот приймає тільки рівні з allowlist Release 1.

Якщо API повертає невідомий рівень, бот:

* не показує його користувачу;
* логує `api_contract_violation`;
* не падає.

---

## 9. Themes Endpoint

## 9.1. Purpose

Themes endpoint повертає теми, доступні для конкретного рівня.

Бот використовує цей endpoint для:

* Theme Selection Screen;
* recommendations;
* progress coverage;
* перевірки, чи можна стартувати тренування.

## 9.2. Recommended Request

```text
GET /levels/{level}/themes?include_counts=true
```

## 9.3. Required Request Parameters

| Parameter | Required | Meaning |
|---|---:|---|
| `level` | Yes | CEFR-рівень. |
| `include_counts` | Should | Чи повертати кількість доступних питань. |
| `active_only` | Should | Чи повертати тільки активні теми. |

## 9.4. Required Response Fields

| Field | Type | Required | Purpose |
|---|---:|---:|---|
| `level` | string | Yes | Рівень каталогу. |
| `themes` | array | Yes | Список тем. |
| `themes[].theme` | string | Yes | Назва теми. |
| `themes[].theme_key` | string | Yes | Стабільний ключ теми. |
| `themes[].available_items_count` | integer | Should | Кількість активних питань. |
| `themes[].is_active` | boolean | Yes | Чи доступна тема. |
| `themes[].metadata` | object | Should | Класифікація теми. |
| `content_version` | string | No | Версія каталогу. |

## 9.5. UX Rule

Бот показує користувачу тільки теми, для яких:

```text
is_active = true
available_items_count > 0
```

Якщо `available_items_count` невідомий, тема може бути показана тільки якщо локальний cache має валідну recent availability.

---

## 10. Availability Endpoint

## 10.1. Purpose

Availability endpoint повертає кількість доступних питань для level + theme.

Цей endpoint потрібен для:

* `coverage`;
* `available_items_count`;
* рекомендацій;
* перевірки перед стартом сесії;
* фільтрації недоступних тем;
* admin diagnostics.

## 10.2. Recommended Request

```text
GET /availability?level=A2&theme=Artikel
```

## 10.3. Required Response Fields

| Field | Type | Required | Purpose |
|---|---:|---:|---|
| `level` | string | Yes | CEFR-рівень. |
| `theme` | string | Yes | Тема. |
| `theme_key` | string | Yes | Стабільний ключ теми. |
| `available_items_count` | integer | Yes | Кількість доступних item. |
| `active_items_count` | integer | Should | Кількість активних item. |
| `inactive_items_count` | integer | No | Кількість вимкнених item. |
| `content_version` | string | No | Версія контенту. |
| `generated_at` | datetime | Yes | Час розрахунку availability. |

## 10.4. Progress Rule

Для Progress Model:

```text
coverage_raw = unique_items_seen / available_items_count
```

Якщо `available_items_count` невідомий:

* `coverage` має статус `unknown`;
* тема не може отримати статус `strong`;
* recommendation engine не має радити тему як повністю покриту;
* система логує `content_metadata_issue`.

---

## 11. Question Batch Endpoint

## 11.1. Purpose

Question batch endpoint повертає питання для тренувальної сесії.

Він використовується для:

* regular session;
* recommended session;
* mistake review session;
* short session, якщо питань недостатньо.

## 11.2. Recommended Request

```text
GET /questions?level=A2&theme=Artikel&count=10&exclude_seen=true
```

## 11.3. Required Request Parameters

| Parameter | Required | Meaning |
|---|---:|---|
| `level` | Yes | CEFR-рівень. |
| `theme` | Yes for regular sessions | Тема тренування. |
| `count` | Yes | Бажана кількість питань. |
| `exclude_seen` | Should | Чи уникати вже бачених item. |
| `exclude_item_ids` | No | Список item, які не треба повертати. |
| `item_ids` | No | Список конкретних item для mistake review. |
| `question_type` | No | Тип питання, якщо потрібен. |
| `difficulty` | No | Цільова складність. |
| `session_type` | Should | `regular`, `mistake_review`, `recommended`. |

## 11.4. User Context Boundary

`user_context` може передаватись тільки як мінімальний навчальний контекст.

Дозволено:

* `seen_item_ids`;
* `mistake_item_ids`;
* `weak_theme_keys`;
* `target_level`;
* `session_type`.

Заборонено без окремої потреби:

* Telegram username;
* first name;
* raw chat history;
* payment data;
* subscription payment identifiers;
* будь-які secrets.

## 11.5. Required Response Fields

| Field | Type | Required | Purpose |
|---|---:|---:|---|
| `items` | array | Yes | Питання для сесії. |
| `items[].item_id` | string | Yes | Стабільний ID питання. |
| `items[].level` | string | Yes | CEFR-рівень. |
| `items[].theme` | string | Yes | Тема. |
| `items[].theme_key` | string | Should | Стабільний ключ теми. |
| `items[].question_text` | string | Yes | Текст питання. |
| `items[].answer_options` | array | Yes | Варіанти відповідей. |
| `items[].correct_answer` | string/object | Yes | Правильна відповідь для backend scoring. |
| `items[].explanation` | string | Yes | Пояснення відповіді. |
| `items[].metadata` | object | Yes | Metadata для прогресу. |
| `items[].content_version` | string | No | Версія питання. |
| `requested_count` | integer | Yes | Скільки питань просив бот. |
| `returned_count` | integer | Yes | Скільки питань повернуло API. |
| `has_more` | boolean | No | Чи є ще питання за фільтрами. |

## 11.6. Answer Option Fields

Кожен варіант відповіді має містити:

| Field | Required | Purpose |
|---|---:|---|
| `option_id` | Yes | Стабільний ID варіанту в межах питання. |
| `text` | Yes | User-facing текст варіанту. |
| `order` | Should | Порядок показу або shuffle support. |

`correct_answer` не має показуватись користувачу до відповіді.

## 11.7. Insufficient Questions Rule

Якщо `returned_count < requested_count`, бот застосовує конфігураційне правило:

| Policy | Behavior |
|---|---|
| `allow_short_session` | Запустити коротшу сесію. |
| `ask_another_theme` | Запропонувати іншу тему. |
| `show_insufficient_state` | Показати insufficient questions state. |

Daily limit списується тільки за фактично видане користувачу питання.

---

## 12. Question Lookup Endpoint

## 12.1. Purpose

Question lookup endpoint повертає конкретне питання за `item_id`.

Він потрібен для:

* mistake review;
* повторного показу питання;
* оновлення metadata snapshot;
* перевірки, чи item досі активний;
* історичного аудиту.

## 12.2. Recommended Request

```text
GET /questions/{item_id}
```

## 12.3. Required Response Fields

Поля відповіді мають відповідати одному `items[]` з Question Batch Endpoint.

Додатково бажані поля:

| Field | Type | Required | Purpose |
|---|---:|---:|---|
| `is_active` | boolean | Yes | Чи можна зараз використовувати item. |
| `replaced_by_item_id` | string | No | Новий item, якщо старий замінено. |
| `deactivated_reason` | string | No | Причина деактивації. |

## 12.4. Mistake Review Rule

Якщо `item_id` з активної помилки більше недоступний:

* бот не видаляє Mistake;
* бот не показує невалідне питання;
* Mistake отримує technical status або flag `content_unavailable`;
* користувачу пропонується інше доступне тренування;
* система логує `mistake_item_unavailable`.

---

## 13. Metadata Endpoint

## 13.1. Purpose

Metadata endpoint повертає словник metadata, які підтримує Quiz Bank.

Він потрібен для:

* валідації metadata в питаннях;
* progress model;
* recommendation logic;
* admin diagnostics;
* contract tests.

## 13.2. Recommended Request

```text
GET /metadata
```

## 13.3. Required Response Fields

| Field | Type | Required | Purpose |
|---|---:|---:|---|
| `levels` | array | Yes | Підтримувані рівні. |
| `themes` | array | Yes | Підтримувані теми. |
| `question_types` | array | Should | Типи питань. |
| `difficulty_scale` | object | Should | Шкала складності. |
| `skill_areas` | array | Should | Граматика, лексика тощо. |
| `metadata_version` | string | Yes | Версія metadata contract. |
| `generated_at` | datetime | Yes | Час генерації словника. |

---

## 14. Required Question Data

Кожне питання, яке бот використовує в сесії, має містити:

| Field | Required | Learning Purpose |
|---|---:|---|
| `item_id` | Yes | Стабільний зв’язок відповіді, помилки й прогресу. |
| `level` | Yes | Розділення прогресу між A1–C1. |
| `theme` | Yes | Progress Topic і рекомендації. |
| `theme_key` | Should | Стабільна агрегація теми незалежно від display name. |
| `question_text` | Yes | User-facing навчальний контент. |
| `answer_options` | Yes | Варіанти відповіді. |
| `correct_answer` | Yes | Scoring і mistake creation. |
| `explanation` | Yes | Feedback після відповіді. |
| `metadata` | Yes | Progress Model, Mistake Model, Recommendation Model. |
| `content_version` | Should | Історичний аудит і cache invalidation. |

Якщо `metadata` відсутня або невалідна, питання не має використовуватись для progress scoring.

---

## 15. Required Metadata for Progress

## 15.1. Core Metadata

| Field | Required | Purpose |
|---|---:|---|
| `progress_theme_key` | Yes | Агрегація в Progress Topic. |
| `learning_objective_id` | Should | Зв’язок з навчальною ціллю. |
| `skill_area` | Should | `grammar`, `vocabulary`, `reading`, `exam`, etc. |
| `question_type` | Should | Тип питання. |
| `difficulty` | Should | Нормалізація складності. |
| `tags` | Should | Додаткова класифікація. |
| `coverage_weight` | Should | Вага item у coverage. |
| `mistake_group_key` | Should | Групування схожих помилок. |
| `repetition_priority` | Should | Базовий сигнал для повторення. |

## 15.2. Progress Metadata Rules

`progress_theme_key` має бути стабільним.

Якщо display name теми змінюється:

```text
theme may change
progress_theme_key must not change
```

Якщо `difficulty` відсутня:

* питання може використовуватись у regular session;
* difficulty-based recommendation не має використовувати це питання;
* система логує metadata warning.

Якщо `mistake_group_key` відсутній:

* Mistake створюється по `item_id`;
* grouping схожих помилок не застосовується;
* це не блокує базове тренування.

## 15.3. Metadata Snapshot

Під час відповіді користувача бот зберігає `metadata_snapshot`.

Мінімальний snapshot:

| Field | Purpose |
|---|---|
| `progress_theme_key` | Прогрес по темі. |
| `skill_area` | Категоризація слабких місць. |
| `question_type` | Аналіз типів питань. |
| `difficulty` | Майбутня адаптація складності. |
| `mistake_group_key` | Групування помилок. |
| `content_version` | Аудит зміни контенту. |

Snapshot потрібен, щоб історичні відповіді не втратили сенс після зміни Quiz Bank.

---

## 16. Data Validation Rules

Бот має валідовувати кожну API response до використання.

## 16.1. Structural Validation

Обов’язково перевіряти:

* HTTP status;
* parseable JSON;
* наявність required fields;
* типи полів;
* порожні масиви там, де потрібні items;
* дублікати `item_id` в одному batch;
* відповідність `level` і `theme` запиту;
* коректність `answer_options`;
* наявність `correct_answer`;
* валідність `metadata`.

## 16.2. Semantic Validation

Бот має відхилити питання, якщо:

* `level` не входить у A1–C1;
* `theme` не відповідає обраній темі для regular session;
* `item_id` порожній;
* `answer_options` не містять мінімально допустиму кількість варіантів;
* `correct_answer` не відповідає жодному option;
* `question_text` порожній;
* metadata не дозволяє оновити progress topic.

## 16.3. Invalid Item Rule

Якщо batch містить частину невалідних item:

* бот відкидає невалідні item;
* невалідні item не показуються користувачу;
* daily limit за них не списується;
* система логує `api_invalid_item`;
* якщо валідних item недостатньо, застосовується insufficient questions rule.

---

## 17. Session Integration Flow

## 17.1. Regular Training Flow

```text
User chooses level/theme
  -> Bot checks daily limit
  -> Bot requests question batch
  -> Bot validates API response
  -> Bot creates Training Session
  -> Bot shows first question
  -> User answers
  -> Bot scores answer
  -> Bot stores User Answer
  -> Bot updates Progress Topic
  -> Bot creates/updates Mistake if needed
  -> Bot charges daily limit for shown question
```

## 17.2. Ordering Rule

Daily limit is charged only after a question is successfully shown to the user.

Forbidden:

```text
Charge daily limit before successful API response.
Charge daily limit for invalid API item.
Charge daily limit after timeout.
Charge daily limit for question that was never shown.
```

## 17.3. Mistake Review Flow

```text
User opens mistake review
  -> Bot loads active Mistakes
  -> Bot requests items by item_id or compatible replacements
  -> Bot validates returned questions
  -> Bot starts mistake_review session
  -> Bot updates Mistake status after answer
```

If an old mistake item is unavailable, bot preserves the mistake record and skips the unavailable item.

## 17.4. Recommendation Flow

```text
Recommendation engine selects weak level/theme
  -> Bot checks Quiz Bank availability
  -> Bot excludes unavailable topics
  -> Bot creates recommendation only for available action
```

Recommendation must not point to unavailable content.

---

## 18. Error Taxonomy

API errors are classified into deterministic categories.

| Category | Examples | User Impact |
|---|---|---|
| `timeout` | Request exceeds timeout. | Retry state. |
| `network_error` | DNS, connection reset, TLS error. | Retry state. |
| `auth_error` | 401, 403. | No user retry loop; admin alert. |
| `not_found` | Item missing. | Skip item or content unavailable. |
| `rate_limited` | 429. | Backoff and retry later. |
| `server_error` | 500–599. | Retry state, circuit breaker signal. |
| `invalid_response` | Missing fields, invalid JSON. | Reject payload, log contract violation. |
| `insufficient_questions` | Fewer items than requested. | Short session or theme change. |
| `content_unavailable` | Theme/item inactive. | Do not recommend or show item. |

---

## 19. Error Handling Rules

## 19.1. User-Facing Rule

Усі user-facing error messages мають бути німецькою.

Standard API error copy:

```text
Etwas ist schiefgelaufen.

Bitte versuche es gleich noch einmal.
```

Buttons:

```text
🔄 Noch einmal versuchen
🏠 Hauptmenü
```

## 19.2. No Raw Error Rule

Бот не має показувати користувачу:

* HTTP status;
* stack trace;
* raw API response;
* API host;
* secret names;
* internal exception messages.

## 19.3. No State Damage Rule

API failure не має:

* списувати daily limit;
* створювати User Answer;
* створювати Mistake;
* завершувати сесію як успішну;
* змінювати Progress Topic;
* показувати paywall як заміну error handling.

## 19.4. Technical Logging Rule

Кожна технічна помилка API має логуватися з мінімальними діагностичними даними:

| Field | Purpose |
|---|---|
| `event_name` | Наприклад, `quiz_bank_api_error`. |
| `request_id` | Кореляція. |
| `endpoint` | Логічний endpoint без secrets. |
| `status_code` | HTTP status, якщо є. |
| `error_category` | Категорія з taxonomy. |
| `level` | Якщо релевантно. |
| `theme` | Якщо релевантно. |
| `session_id` | Якщо сесія вже створена. |
| `user_id` | Internal user id, якщо потрібен для діагностики. |
| `occurred_at` | Час помилки. |

Логи не мають містити API key, raw authorization header або повний dump response з потенційно чутливими даними.

---

## 20. Retry Policy

## 20.1. Safe Retry Scope

Retry дозволений для read-only endpoint-ів:

* `/health`;
* `/levels`;
* `/levels/{level}/themes`;
* `/availability`;
* `/questions`;
* `/questions/{item_id}`;
* `/metadata`.

## 20.2. Retry Rules

Рекомендована policy:

| Error | Retry |
|---|---|
| `timeout` | Yes, короткий retry з backoff. |
| `network_error` | Yes, короткий retry з backoff. |
| `rate_limited` | Retry only after delay or not in user flow. |
| `server_error` | Yes, limited retry. |
| `auth_error` | No. |
| `invalid_response` | No. |
| `not_found` | No. |

## 20.3. User Flow Constraint

Retry не має затримувати Telegram-відповідь надмірно.

Базова ціль:

```text
Question fetch should complete within 3 seconds.
```

Якщо retry не вкладається в UX budget, бот показує API Error State.

---

## 21. Temporary API Unavailability

## 21.1. Definition

API вважається тимчасово недоступним, якщо:

* health endpoint повертає `unavailable`;
* більшість recent API calls завершуються `timeout` або `server_error`;
* circuit breaker відкритий;
* Quiz Bank повертає maintenance status;
* DNS/TLS/network failure триває довше одного user action.

## 21.2. Required Bot Behavior

Якщо API тимчасово недоступний, бот має:

* не стартувати нову API-залежну сесію без валідного fallback;
* показати німецьке error message;
* не списувати daily limit;
* не створювати answer records;
* не змінювати progress;
* не закривати mistakes;
* записати технічну помилку;
* дозволити користувачу повернутися в Home.

## 21.3. Allowed Fallbacks

Дозволені fallback-и:

| Fallback | Allowed | Conditions |
|---|---:|---|
| Theme catalog cache | Yes | Cache valid, TTL не минув. |
| Availability cache | Yes | Тільки для UX filtering і recommendations. |
| Recently fetched question buffer | Conditional | Тільки якщо item вже валідований, ще не показаний і cache policy дозволяє. |
| Full local question bank | No | Порушує ownership rule. |
| Fake/generated questions | No | Порушує Quiz Bank source-of-truth. |
| Paywall instead of error | No | Порушує monetization rules. |

## 21.4. User-Facing Copy

Standard temporary unavailable copy:

```text
Etwas ist schiefgelaufen.

Bitte versuche es gleich noch einmal.
```

If content is unavailable for a theme:

```text
Für dieses Thema gibt es gerade nicht genug Fragen.

Bitte wähle ein anderes Thema.
```

Buttons:

```text
🎯 Thema wählen
🏠 Hauptmenü
```

---

## 22. Cache Policy

## 22.1. Cache Purpose

Cache потрібен для:

* швидкого показу тем;
* зменшення залежності від transient API failures;
* progress coverage;
* recommendations;
* admin diagnostics.

Cache не має перетворюватися на локальний Quiz Bank.

## 22.2. Cacheable Data

| Data | Cache Allowed | Notes |
|---|---:|---|
| Levels catalog | Yes | Низька частота змін. |
| Themes catalog | Yes | Потрібно для UX. |
| Availability counts | Yes | Потрібно для coverage. |
| Metadata catalog | Yes | Потрібно для validation. |
| Question batch | Conditional | Тільки короткий buffer для активної сесії. |
| Full question bank | No | Заборонено. |

## 22.3. TTL Guidelines

| Cache | Suggested TTL | Failure Behavior |
|---|---:|---|
| Levels | 24 hours | Використати stale тільки для navigation. |
| Themes | 1–6 hours | Використати stale для Theme Selection з caution. |
| Availability | 15–60 minutes | Якщо stale, coverage confidence знижується. |
| Metadata | 24 hours | Contract warning, якщо version mismatch. |
| Session question buffer | Active session only | Видалити після завершення або abandon. |

TTL є launch configuration, а не hardcoded product rule.

## 22.4. Cache Invalidation

Cache має оновлюватись, якщо:

* `content_version` змінився;
* `metadata_version` змінився;
* API повернув item як inactive;
* admin manually invalidates cache;
* TTL минув.

---

## 23. Circuit Breaker

## 23.1. Purpose

Circuit breaker захищає Telegram UX від повторних повільних API failures.

## 23.2. States

| State | Meaning | Bot Behavior |
|---|---|---|
| `closed` | API працює. | Normal requests. |
| `open` | API failure rate high. | Не робити user-flow API calls, показувати fallback/error. |
| `half_open` | Перевірка відновлення. | Обмежена кількість test requests. |

## 23.3. User Impact Rule

Користувач не має чекати повний timeout знову і знову, якщо система вже знає, що API недоступний.

---

## 24. Analytics Events

## 24.1. Required API Events

| Event | Trigger |
|---|---|
| `quiz_api_request_started` | Перед API request. |
| `quiz_api_request_succeeded` | Після валідної response. |
| `quiz_api_request_failed` | Після technical failure. |
| `quiz_api_invalid_response` | Schema або semantic validation failed. |
| `quiz_api_insufficient_questions` | API повернув менше item, ніж потрібно. |
| `quiz_api_unavailable_shown` | Користувачу показано API error state. |
| `quiz_api_cache_used` | Використано cache замість live response. |

## 24.2. Event Metadata

API analytics metadata має містити:

| Field | Purpose |
|---|---|
| `endpoint` | Логічний endpoint. |
| `level` | Якщо релевантно. |
| `theme` | Якщо релевантно. |
| `requested_count` | Для question batch. |
| `returned_count` | Для question batch. |
| `duration_ms` | Performance diagnostics. |
| `error_category` | Для failures. |
| `cache_hit` | Cache diagnostics. |
| `content_version` | Content traceability. |

Analytics не має містити secrets або raw authorization data.

---

## 25. Admin Metrics

Адмінська статистика має показувати:

* API errors today;
* timeout count;
* invalid response count;
* insufficient questions count;
* most affected levels;
* most affected themes;
* average API latency;
* cache hit rate;
* content metadata issues;
* unavailable item count for mistake review.

Ці метрики потрібні для контролю якості Quiz Bank і стабільності продукту.

---

## 26. Security and Privacy Rules

## 26.1. Secret Handling

Заборонено:

* комітити API keys;
* логувати `Authorization`;
* показувати API errors як raw text;
* передавати secrets у callback data;
* включати secrets у analytics metadata.

## 26.2. User Data Minimization

Quiz Bank API не має отримувати Telegram PII, якщо це не потрібно для контенту.

Preferred user context:

```text
internal learning context, not identity context
```

## 26.3. Response Trust Boundary

Кожна API response є зовнішнім input.

До валідації її не можна:

* показувати користувачу;
* зберігати як trusted snapshot;
* використовувати для progress scoring;
* використовувати для mistake resolution;
* використовувати для recommendation.

---

## 27. Contract Test Requirements

## 27.1. Required Tests

Integration має покриватися такими test categories:

| Test | Purpose |
|---|---|
| Health response validation | API status parsing. |
| Levels contract | Supported CEFR levels. |
| Themes contract | Required theme fields. |
| Availability contract | `available_items_count` correctness. |
| Question batch contract | Required question fields. |
| Metadata contract | Progress metadata presence. |
| Invalid response handling | Safe rejection. |
| Timeout handling | No daily limit charge. |
| Insufficient questions handling | Configured policy. |
| Cache fallback handling | Valid TTL and scope. |

## 27.2. Mock Data Rule

Test fixtures may contain minimal sample questions.

Fixtures must be:

* small;
* clearly marked as test data;
* not a copy of production Quiz Bank;
* sufficient only for contract and behavior tests.

---

## 28. Acceptance Criteria

API integration is acceptable for Release 1 if:

1. Бот отримує питання з Quiz Bank API.
2. Бот не дублює Quiz Bank як локальний банк.
3. Бот показує тільки доступні рівні й теми.
4. Бот валідовує API responses перед використанням.
5. Кожне видане питання має `item_id`, `level`, `theme`, `answer_options`, `correct_answer`, `explanation` і `metadata`.
6. Progress Model отримує `available_items_count` або ставить coverage у `unknown`.
7. API failure не списує daily limit.
8. API failure не створює User Answer.
9. API failure не створює Mistake.
10. API failure не пошкоджує active session.
11. Тимчасова недоступність API показує німецький error state.
12. Insufficient questions обробляються за конфігураційним правилом.
13. Technical API errors логуються без secrets.
14. Cache має визначений TTL і не стає full question bank.
15. Recommendation не радить недоступний контент.

---

## 29. Non-Goals

Цей документ не визначає:

* фінальний backend framework;
* фінальну бібліотеку HTTP client;
* database schema;
* payment provider API;
* Telegram webhook architecture;
* production hostnames;
* реальні API keys;
* остаточну OpenAPI schema.

Ці рішення мають бути прийняті окремо в технічному дизайні після вибору стеку.

---

## 30. Integration Invariants

1. API Quiz Bank is the canonical source of learning content.
2. Deutsch Trainer Bot stores learning state, not the full content bank.
3. Every API response is validated before use.
4. Every shown question has a stable `item_id`.
5. Every answer stores enough snapshot data for historical meaning.
6. Daily limit is charged only for a question shown to the user.
7. API failure never creates fake progress.
8. API failure never becomes a paywall trigger.
9. Metadata quality directly affects progress confidence.
10. Unavailable content must not be recommended.
11. User-facing API error copy is always German.
12. Secrets never appear in logs, analytics, Telegram messages or committed files.
