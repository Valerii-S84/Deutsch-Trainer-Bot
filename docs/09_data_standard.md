# Deutsch Trainer Bot — Data Standard

## 1. Document Purpose

Цей документ описує стандарт даних **Deutsch Trainer Bot**.

Він фіксує:

* логічні таблиці;
* обов’язкові поля;
* статуси;
* правила збереження відповідей;
* правила збереження помилок;
* правила підписок і платежів;
* правила історії прогресу;
* інваріанти цілісності даних.

Документ не є SQL migration, ORM schema або фізичною моделлю конкретної бази даних.

Його мета — задати строгий, перевірюваний і презентаційно зрозумілий стандарт, який можна перетворити на ERD, database schema, migrations, repositories, fixtures і tests.

---

## 2. Modeling Standard

Data Standard описаний у строгому академічному форматі.

У межах цього документа **Stanford-level standard** означає:

* кожна таблиця має одну чітку відповідальність;
* кожне поле має визначене призначення;
* кожен статус має явний зміст;
* кожен lifecycle має допустимі переходи;
* кожна write-operation має idempotency rule;
* кожна агрегована метрика має джерело даних;
* кожна історична зміна має audit або history rule;
* кожна зовнішня reference має ownership boundary;
* кожне правило придатне для unit, integration або data integrity tests.

Головний принцип:

> Дані мають доводити, що користувач реально тренувався, реально відповідав і реально отримав доступ, а не лише що система показала екран.

---

## 3. Data Ownership Boundary

## 3.1. Internal Data

Deutsch Trainer Bot володіє:

* users;
* training sessions;
* question references;
* user answers;
* progress topics;
* progress history;
* mistakes;
* mistake history;
* recommendations;
* daily limits;
* subscriptions;
* payments;
* analytics events;
* API error logs.

## 3.2. External Data

API Quiz Bank володіє:

* canonical question content;
* answer options;
* correct answer;
* explanation;
* content metadata;
* content version;
* availability counts.

## 3.3. Snapshot Rule

Бот може зберігати тільки мінімальні snapshots, потрібні для:

* історії відповіді;
* журналу помилок;
* progress calculation;
* audit;
* стабільності після зміни Quiz Bank content.

Бот не має ставати повною локальною копією Quiz Bank.

---

## 4. Naming and Type Conventions

## 4.1. Table Naming

Логічні таблиці називаються у plural snake_case:

```text
users
training_sessions
user_answers
progress_topics
mistakes
subscriptions
```

## 4.2. Field Naming

Поля називаються у snake_case.

Рекомендовані suffix-и:

| Suffix | Meaning |
|---|---|
| `_id` | Internal identifier or foreign key. |
| `_at` | Timestamp. |
| `_date` | Calendar date. |
| `_count` | Integer counter. |
| `_score` | Normalized score 0–100. |
| `_status` | Controlled enum status. |
| `_snapshot` | Historical copy of external data. |
| `_metadata` | Structured JSON object. |

## 4.3. Timestamp Standard

Усі timestamps зберігаються як absolute time.

Базове правило:

```text
stored timestamps must be timezone-safe
```

Business-day logic для daily limit і recency використовує:

```text
Europe/Berlin
```

## 4.4. Identifier Standard

Кожна таблиця має internal `id`, крім якщо фізична реалізація явно використовує composite primary key.

External identifiers зберігаються окремо:

| Field | Source |
|---|---|
| `telegram_user_id` | Telegram. |
| `item_id` | Quiz Bank API. |
| `provider_payment_id` | Telegram Stars provider. |
| `provider_reference` | Subscription/payment provider. |

External ID не має підміняти internal ownership.

---

## 5. Logical Table Overview

| Table | Purpose | Owns State |
|---|---|---:|
| `users` | Telegram-користувач і поточний навчальний стан. | Yes |
| `training_sessions` | Навчальна сесія користувача. | Yes |
| `training_session_items` | Питання, реально видані або підготовлені в межах сесії. | Yes |
| `question_references` | Мінімальне посилання на Quiz Bank item. | Limited |
| `user_answers` | Факт відповіді користувача. | Yes |
| `progress_topics` | Агрегований поточний прогрес по level + theme. | Yes |
| `progress_history` | Append-only історія змін прогресу. | Yes |
| `mistakes` | Поточний стан помилки. | Yes |
| `mistake_history` | Append-only історія подій помилки. | Yes |
| `recommendations` | Згенерована рекомендація. | Yes |
| `daily_limits` | Денне використання питань. | Yes |
| `subscriptions` | Історія й поточний статус доступу. | Yes |
| `payments` | Платіжні операції та idempotent credit. | Yes |
| `analytics_events` | Продуктові, навчальні й технічні події. | Append-only |
| `api_error_logs` | Діагностика Quiz Bank API failures. | Append-only |

---

## 6. Users

## 6.1. Purpose

`users` зберігає Telegram-користувача та його поточний навчальний стан.

## 6.2. Required Fields

| Field | Required | Meaning |
|---|---:|---|
| `id` | Yes | Internal user ID. |
| `telegram_user_id` | Yes | Telegram user ID. |
| `username` | No | Telegram username, якщо доступний. |
| `first_name` | No | Telegram first name, якщо доступний. |
| `language_code` | No | Telegram language code. |
| `selected_level` | No | Поточний CEFR-рівень. |
| `selected_theme` | No | Поточна тема. |
| `subscription_status` | Yes | Current access summary. |
| `active_session_id` | No | Поточна активна сесія, якщо є. |
| `created_at` | Yes | Час створення користувача. |
| `updated_at` | Yes | Час оновлення. |
| `last_active_at` | Yes | Остання активність. |

## 6.3. Constraints

| Constraint | Rule |
|---|---|
| Unique Telegram user | `telegram_user_id` має бути унікальним. |
| Supported level | `selected_level` має бути `A1`, `A2`, `B1`, `B2`, `C1` або null. |
| Active session ownership | `active_session_id` має належати цьому ж user. |

## 6.4. Invariants

* Returning Telegram user не створює дубль.
* `last_active_at` оновлюється після meaningful user interaction.
* User deletion не входить у Release 1 data flow.
* User-facing language зберігається як context, але UI copy все одно має бути німецькою.

---

## 7. Training Sessions

## 7.1. Purpose

`training_sessions` групує питання й відповіді в одну навчальну взаємодію.

## 7.2. Required Fields

| Field | Required | Meaning |
|---|---:|---|
| `id` | Yes | Internal session ID. |
| `user_id` | Yes | Власник сесії. |
| `level` | Yes | Рівень сесії. |
| `theme` | No | Тема сесії, якщо session type потребує тему. |
| `session_type` | Yes | Тип сесії. |
| `status` | Yes | Поточний статус. |
| `started_at` | Yes | Час старту. |
| `completed_at` | No | Час завершення. |
| `abandoned_at` | No | Час виходу або abandon. |
| `failed_at` | No | Час технічного failure. |
| `total_questions` | Yes | Кількість запланованих або виданих питань. |
| `shown_questions_count` | Yes | Кількість реально показаних питань. |
| `answered_count` | Yes | Кількість прийнятих відповідей. |
| `correct_answers` | Yes | Кількість правильних відповідей. |
| `api_request_id` | No | Correlation з Quiz Bank request. |
| `created_at` | Yes | Час створення. |
| `updated_at` | Yes | Час оновлення. |

## 7.3. Session Types

| Type | Meaning |
|---|---|
| `regular` | Звичайне тренування за level + theme. |
| `mistake_review` | Повторення активних помилок. |
| `recommended` | Сесія з рекомендації. |

## 7.4. Statuses

| Status | Meaning |
|---|---|
| `created` | Сесія створена, але питання ще не видане. |
| `active` | Сесія триває. |
| `completed` | Користувач відповів на всі доступні питання сесії. |
| `abandoned` | Користувач явно або фактично вийшов із сесії. |
| `failed` | Сесія не може бути продовжена через технічну помилку. |

## 7.5. Transition Rules

```text
created -> active
active -> completed
active -> abandoned
active -> failed
created -> failed
```

Forbidden:

```text
completed -> active
abandoned -> active
failed -> completed
```

## 7.6. Invariants

* Сесія належить рівно одному User.
* `correct_answers <= answered_count`.
* `answered_count <= shown_questions_count`.
* Завершена сесія не приймає нові відповіді.
* API failure не списує daily limit без показаного питання.

---

## 8. Question References

## 8.1. Purpose

`question_references` зберігає мінімальний внутрішній reference на item з Quiz Bank API.

Це не локальна копія банку питань.

## 8.2. Required Fields

| Field | Required | Meaning |
|---|---:|---|
| `id` | Yes | Internal reference ID. |
| `item_id` | Yes | Canonical Quiz Bank item ID. |
| `level` | Yes | Рівень питання. |
| `theme` | Yes | Тема питання. |
| `theme_key` | No | Стабільний ключ теми. |
| `source` | Yes | `quiz_bank_api`. |
| `metadata_snapshot` | Yes | Metadata на момент отримання. |
| `content_version` | No | Версія контенту. |
| `question_text_snapshot` | No | Мінімальний текстовий snapshot. |
| `correct_answer_snapshot` | No | Правильна відповідь на момент відповіді. |
| `explanation_snapshot` | No | Пояснення на момент відповіді. |
| `fetched_at` | Yes | Коли item отримано. |
| `created_at` | Yes | Час створення reference. |
| `updated_at` | Yes | Час оновлення reference. |

## 8.3. Constraints

| Constraint | Rule |
|---|---|
| Unique item | `item_id` має бути унікальним або версіонованим через `item_id + content_version`. |
| Source | `source = quiz_bank_api` для Release 1. |
| Supported level | `level` має бути A1–C1. |

## 8.4. Invariants

* Question Reference не створюється для довільного локального питання.
* Snapshot зберігається тільки для історії, повторення, аудиту або progress consistency.
* Якщо Quiz Bank змінює item, історичні відповіді й помилки не втрачають сенс.

---

## 8.5. Training Session Items

## 8.5.1. Purpose

`training_session_items` зберігає item-и, які підготовлені або реально показані в межах конкретної сесії.

Ця таблиця потрібна для доказу:

* яке питання було видане;
* у якій позиції сесії;
* чи було питання реально показане;
* чи можна приймати відповідь;
* чи треба списувати Daily Limit;
* чи є відповідь duplicate.

## 8.5.2. Required Fields

| Field | Required | Meaning |
|---|---:|---|
| `id` | Yes | Internal session item ID. |
| `session_id` | Yes | Training Session. |
| `user_id` | Yes | Користувач. |
| `question_reference_id` | Yes | Question Reference. |
| `item_id` | Yes | Quiz Bank item ID. |
| `position` | Yes | Позиція питання в сесії. |
| `status` | Yes | Стан item у сесії. |
| `shown_at` | No | Коли питання реально показане користувачу. |
| `answered_at` | No | Коли прийнята відповідь. |
| `daily_limit_charged_at` | No | Коли списаний daily limit. |
| `created_at` | Yes | Час створення. |
| `updated_at` | Yes | Час оновлення. |

## 8.5.3. Statuses

| Status | Meaning |
|---|---|
| `prepared` | Item отримано з API і валідовано, але ще не показано. |
| `shown` | Item реально показано користувачу. |
| `answered` | Відповідь прийнята. |
| `skipped` | Item пропущено без відповіді за безпечним правилом. |
| `invalid` | Item відхилено через validation або content issue. |

## 8.5.4. Constraints

| Constraint | Rule |
|---|---|
| Unique position | `session_id + position` має бути унікальним. |
| Unique item in session | `session_id + item_id` має бути унікальним. |
| Answer eligibility | User Answer можна створити тільки для item зі status `shown` або `answered` через idempotent повтор. |
| Daily limit charge | Daily Limit списується один раз на `training_session_item`. |

## 8.5.5. Show Question Rule

Коли питання реально показане користувачу:

1. `training_session_items.status` переходить у `shown`.
2. Заповнюється `shown_at`.
3. Daily Limit списується, якщо ще не списаний.
4. Заповнюється `daily_limit_charged_at`.
5. Training Session збільшує `shown_questions_count`.

Якщо API failure стався до показу питання, `shown_at` не заповнюється і Daily Limit не списується.

---

## 9. User Answers

## 9.1. Purpose

`user_answers` зберігає факт відповіді користувача на конкретне питання в конкретній сесії.

Це головне джерело для:

* accuracy;
* coverage;
* stability;
* weakness;
* mistake creation;
* recommendation;
* learning analytics.

## 9.2. Required Fields

| Field | Required | Meaning |
|---|---:|---|
| `id` | Yes | Internal answer ID. |
| `user_id` | Yes | Користувач. |
| `session_id` | Yes | Training Session. |
| `training_session_item_id` | Yes | Item сесії, на який дана відповідь. |
| `question_reference_id` | Yes | Internal Question Reference. |
| `item_id` | Yes | Quiz Bank item ID snapshot. |
| `level` | Yes | Рівень на момент відповіді. |
| `theme` | Yes | Тема на момент відповіді. |
| `theme_key` | No | Стабільний ключ теми. |
| `selected_answer` | Yes | Вибір користувача. |
| `correct_answer` | Yes | Правильна відповідь на момент перевірки. |
| `is_correct` | Yes | Результат відповіді. |
| `response_time_ms` | No | Час відповіді. |
| `session_type` | Yes | Тип сесії. |
| `metadata_snapshot` | Yes | Metadata для progress. |
| `telegram_update_id` | No | Telegram idempotency input. |
| `answered_at` | Yes | Час відповіді. |
| `created_at` | Yes | Час запису. |

## 9.3. Idempotency Constraints

Один користувач може мати тільки одну прийняту відповідь на один item у межах однієї сесії.

Рекомендовані унікальні ключі:

| Key | Purpose |
|---|---|
| `user_id + session_id + item_id` | Захист від повторної відповіді на те саме питання. |
| `telegram_update_id` | Захист від duplicate Telegram update, якщо доступний. |

## 9.4. Save Answer Rule

Прийнята відповідь зберігається в такому порядку:

1. Перевірити, що User існує.
2. Перевірити, що Training Session існує й активна.
3. Перевірити, що `training_session_item` існує і питання було реально показане користувачу.
4. Перевірити idempotency key.
5. Перевірити Question Reference.
6. Створити User Answer.
7. Оновити counters Training Session.
8. Позначити `training_session_item` як `answered`.
9. Оновити Progress Topic.
10. Створити або оновити Mistake, якщо відповідь неправильна.
11. Записати Progress History.
12. Записати Analytics Event.

## 9.5. Duplicate Answer Rule

Якщо відповідь є duplicate:

* новий `user_answers` record не створюється;
* Daily Limit не списується вдруге;
* Progress Topic не оновлюється вдруге;
* Mistake не оновлюється вдруге;
* система може повернути вже обчислений result state.

## 9.6. API Failure Rule

Якщо питання не було отримане або показане через API failure:

* User Answer не створюється;
* Progress Topic не оновлюється;
* Mistake не створюється;
* Daily Limit не списується;
* Training Session може лишитись `active` або перейти в `failed` за session policy;
* технічна помилка записується в `api_error_logs`.

---

## 10. Progress Topics

## 10.1. Purpose

`progress_topics` зберігає поточний агрегований стан знань користувача по парі:

```text
User + Level + Theme
```

## 10.2. Required Fields

| Field | Required | Meaning |
|---|---:|---|
| `id` | Yes | Internal progress ID. |
| `user_id` | Yes | Користувач. |
| `level` | Yes | CEFR-рівень. |
| `theme` | Yes | Тема. |
| `theme_key` | No | Стабільний ключ теми. |
| `accuracy_score` | Yes | Score 0–100. |
| `coverage_score` | No | Score 0–100 або null, якщо unknown. |
| `coverage_status` | Yes | `known` або `unknown`. |
| `stability_score` | Yes | Score 0–100. |
| `weakness_score` | Yes | Score 0–100. |
| `recency_score` | No | Score 0–100, якщо використовується. |
| `topic_status` | Yes | Product-facing status. |
| `answered_count` | Yes | Кількість відповідей. |
| `correct_count` | Yes | Кількість правильних відповідей. |
| `wrong_count` | Yes | Кількість неправильних відповідей. |
| `unique_items_seen` | Yes | Кількість унікальних item_id. |
| `available_items_count` | No | Count з Quiz Bank. |
| `last_practiced_at` | No | Остання відповідь у темі. |
| `last_wrong_at` | No | Остання неправильна відповідь. |
| `last_recalculated_at` | Yes | Останній перерахунок. |
| `created_at` | Yes | Час створення. |
| `updated_at` | Yes | Час оновлення. |

## 10.3. Topic Statuses

| Status | Meaning |
|---|---|
| `new` | Недостатньо даних. |
| `weak` | Низька accuracy або повторні помилки. |
| `learning` | Є прогрес, але тема ще нестабільна. |
| `stable` | Користувач стабільно відповідає правильно. |
| `strong` | Висока accuracy, coverage і stability. |

## 10.4. Constraints

| Constraint | Rule |
|---|---|
| Unique topic | Один `user_id + level + theme` має мати один active Progress Topic. |
| Score range | Score поля мають бути 0–100 або null там, де дозволено unknown. |
| Counts | `correct_count + wrong_count <= answered_count`. |
| Coverage unknown | Якщо `available_items_count` невідомий, `coverage_status = unknown`. |

## 10.5. Update Rule

Progress Topic оновлюється після кожної accepted User Answer.

Правильна відповідь:

* збільшує `answered_count`;
* збільшує `correct_count`;
* може збільшити `unique_items_seen`;
* оновлює accuracy;
* може підвищити stability;
* може знизити weakness;
* оновлює `last_practiced_at`.

Неправильна відповідь:

* збільшує `answered_count`;
* збільшує `wrong_count`;
* може збільшити `unique_items_seen`;
* знижує accuracy;
* підвищує weakness;
* оновлює `last_wrong_at`;
* створює або оновлює Mistake.

## 10.6. Strong Status Rule

Тема не може бути `strong`, якщо:

* `coverage_status = unknown`;
* `coverage_score` недостатній;
* `stability_score` недостатній;
* є значні unresolved mistakes;
* confidence недостатній.

---

## 11. Progress History

## 11.1. Purpose

`progress_history` зберігає append-only історію змін Progress Topic.

Вона потрібна для:

* аудиту progress changes;
* графіків прогресу;
* відновлення причин зміни status;
* аналізу деградації після повторних помилок;
* майбутньої розширеної статистики Plus/Pro.

## 11.2. Required Fields

| Field | Required | Meaning |
|---|---:|---|
| `id` | Yes | Internal history ID. |
| `progress_topic_id` | Yes | Progress Topic. |
| `user_id` | Yes | Користувач. |
| `session_id` | No | Сесія, яка спричинила зміну. |
| `user_answer_id` | No | Відповідь, яка спричинила зміну. |
| `level` | Yes | Рівень. |
| `theme` | Yes | Тема. |
| `event_type` | Yes | Тип зміни. |
| `previous_status` | No | Попередній topic status. |
| `new_status` | Yes | Новий topic status. |
| `previous_scores` | No | Snapshot попередніх score. |
| `new_scores` | Yes | Snapshot нових score. |
| `delta` | No | Зміна score/counters. |
| `reason_code` | Yes | Чому зміна сталася. |
| `created_at` | Yes | Час історичної події. |

## 11.3. Event Types

| Event Type | Meaning |
|---|---|
| `answer_recorded` | Прийнята відповідь оновила прогрес. |
| `mistake_created` | Нова помилка вплинула на тему. |
| `mistake_repeated` | Повторна помилка підвищила weakness. |
| `mistake_improved` | Успішне повторення покращило stability. |
| `mistake_resolved` | Помилка закрита. |
| `coverage_updated` | Змінився `available_items_count` або coverage. |
| `recency_recalculated` | Recency перераховано без нової відповіді. |
| `status_recalculated` | Статус перераховано системно. |

## 11.4. Append-Only Rule

`progress_history` є append-only.

Заборонено:

* змінювати старий history record для переписування результату;
* видаляти history після expiration subscription;
* підміняти відсутність history поточним Progress Topic.

Якщо потрібна корекція, створюється нова compensating history event.

---

## 12. Mistakes

## 12.1. Purpose

`mistakes` зберігає поточний стан помилки користувача.

Помилка є навчальним об’єктом, а не просто log неправильних відповідей.

## 12.2. Required Fields

| Field | Required | Meaning |
|---|---:|---|
| `id` | Yes | Internal mistake ID. |
| `user_id` | Yes | Користувач. |
| `question_reference_id` | Yes | Question Reference. |
| `item_id` | Yes | Quiz Bank item ID. |
| `level` | Yes | Рівень. |
| `theme` | Yes | Тема. |
| `theme_key` | No | Стабільний ключ теми. |
| `wrong_answer` | Yes | Остання неправильна відповідь. |
| `correct_answer` | Yes | Правильна відповідь. |
| `mistake_count` | Yes | Кількість неправильних відповідей. |
| `successful_repeats_count` | Yes | Кількість правильних повторень. |
| `successful_repeat_days_count` | Yes | Кількість днів з правильним повторенням. |
| `status` | Yes | Статус помилки. |
| `first_mistake_at` | Yes | Перша помилка. |
| `last_mistake_at` | Yes | Остання неправильна відповідь. |
| `last_repeated_at` | No | Останнє повторення. |
| `last_successful_repeat_at` | No | Останнє успішне повторення. |
| `resolved_at` | No | Час resolution. |
| `content_available` | Yes | Чи доступний item у Quiz Bank. |
| `created_at` | Yes | Час створення. |
| `updated_at` | Yes | Час оновлення. |

## 12.3. Statuses

| Status | Meaning |
|---|---|
| `new` | Помилка створена після першої неправильної відповіді. |
| `repeated` | Користувач знову помилився в цьому item або темі. |
| `improved` | Користувач відповів правильно під час повторення, але доказ ще недостатній. |
| `resolved` | Користувач правильно повторив помилку кілька разів у різні дні. |

## 12.4. Constraints

| Constraint | Rule |
|---|---|
| Active mistake uniqueness | Один user не має мати дві active mistakes для одного `item_id`. |
| Count floor | `mistake_count >= 1`. |
| Repeat floor | `successful_repeats_count >= 0`. |
| Resolution timestamp | `resolved_at` заповнюється тільки для `resolved`. |

## 12.5. Mistake Save Rule

Після неправильної accepted User Answer:

1. Знайти active Mistake за `user_id + item_id`.
2. Якщо Mistake не існує, створити зі status `new`.
3. Якщо Mistake існує, оновити `wrong_answer`, `last_mistake_at`, `mistake_count`.
4. Якщо попередній status був `resolved`, перевести в `repeated`.
5. Якщо попередній status був `new`, `repeated` або `improved`, застосувати transition rule.
6. Записати `mistake_history`.
7. Оновити Progress Topic weakness/stability.
8. Записати Progress History.

## 12.6. Correct Repeat Rule

Після правильної відповіді у `mistake_review`:

* збільшити `successful_repeats_count`;
* оновити `successful_repeat_days_count`;
* оновити `last_successful_repeat_at`;
* перевести `new` або `repeated` у `improved`;
* перевести `improved` у `resolved` тільки якщо threshold виконано;
* записати `mistake_history`;
* оновити Progress Topic.

## 12.7. Resolution Rule

Release 1 resolution threshold:

```text
resolved requires:
  successful_repeats_count >= 3
  AND successful_repeat_days_count >= 2
  AND last_mistake_at is before the successful repeat sequence
```

Одна правильна відповідь не закриває Mistake.

---

## 13. Mistake History

## 13.1. Purpose

`mistake_history` зберігає append-only події життєвого циклу помилки.

Вона потрібна для:

* аудиту mistake resolution;
* пояснення, чому помилка active або resolved;
* аналізу повторних помилок;
* майбутньої розширеної статистики.

## 13.2. Required Fields

| Field | Required | Meaning |
|---|---:|---|
| `id` | Yes | Internal history ID. |
| `mistake_id` | Yes | Mistake. |
| `user_id` | Yes | Користувач. |
| `user_answer_id` | No | Відповідь, яка спричинила подію. |
| `session_id` | No | Сесія. |
| `item_id` | Yes | Quiz Bank item ID. |
| `event_type` | Yes | Тип події. |
| `previous_status` | No | Попередній status. |
| `new_status` | Yes | Новий status. |
| `wrong_answer` | No | Неправильна відповідь, якщо є. |
| `correct_answer` | No | Правильна відповідь, якщо є. |
| `metadata_snapshot` | No | Metadata на момент події. |
| `created_at` | Yes | Час події. |

## 13.3. Event Types

| Event Type | Meaning |
|---|---|
| `created` | Помилка створена. |
| `wrong_again` | Користувач повторно помилився. |
| `correct_repeat` | Успішне повторення. |
| `improved` | Статус перейшов у improved. |
| `resolved` | Помилка закрита. |
| `reopened` | Resolved mistake знову стала active. |
| `content_unavailable` | Item більше недоступний у Quiz Bank. |

## 13.4. Append-Only Rule

`mistake_history` не редагується заднім числом.

Поточний стан зберігається в `mistakes`, а доказ переходів — у `mistake_history`.

---

## 14. Daily Limits

## 14.1. Purpose

`daily_limits` зберігає денне використання питань користувачем.

## 14.2. Required Fields

| Field | Required | Meaning |
|---|---:|---|
| `id` | Yes | Internal daily limit ID. |
| `user_id` | Yes | Користувач. |
| `plan` | Yes | План на момент ліміту. |
| `limit_date` | Yes | Date у Europe/Berlin. |
| `timezone` | Yes | `Europe/Berlin`. |
| `question_limit` | Yes | Денний ліміт. |
| `questions_used` | Yes | Реально видані питання. |
| `reset_at` | Yes | Наступний reset timestamp. |
| `created_at` | Yes | Час створення. |
| `updated_at` | Yes | Час оновлення. |

## 14.3. Constraints

| Constraint | Rule |
|---|---|
| Unique day | Один `user_id + limit_date + plan` або один active daily record за policy. |
| Counter bounds | `0 <= questions_used <= question_limit`, крім явно заданого paid overflow. |
| Timezone | `limit_date` рахується тільки за Europe/Berlin. |

## 14.4. Counting Rule

Ліміт списується тільки коли питання реально показане користувачу.

Ліміт не списується, якщо:

* API Quiz Bank недоступний;
* API повернув error;
* питання не було показане;
* Telegram update duplicate;
* користувач натиснув застарілу кнопку;
* payment flow був перерваний.

---

## 15. Subscriptions

## 15.1. Purpose

`subscriptions` зберігає історію доступу користувача до Free, Plus і Pro.

## 15.2. Required Fields

| Field | Required | Meaning |
|---|---:|---|
| `id` | Yes | Internal subscription ID. |
| `user_id` | Yes | Користувач. |
| `plan` | Yes | `free`, `plus`, `pro`. |
| `status` | Yes | Статус підписки. |
| `started_at` | No | Початок дії. |
| `expires_at` | No | Завершення дії. |
| `provider` | No | Payment/subscription provider. |
| `provider_reference` | No | Provider reference. |
| `payment_id` | No | Payment, який активував підписку. |
| `cancelled_at` | No | Час скасування. |
| `created_at` | Yes | Час створення. |
| `updated_at` | Yes | Час оновлення. |

## 15.3. Plans

| Plan | Meaning |
|---|---|
| `free` | Базовий доступ з денним лімітом. |
| `plus` | Повний прогрес, журнал помилок, повторення помилок, більший ліміт. |
| `pro` | Розширена статистика й найбільший ліміт. |

## 15.4. Statuses

| Status | Meaning |
|---|---|
| `pending` | Очікується підтвердження платежу або активації. |
| `active` | Доступ активний. |
| `expired` | Період дії завершився. |
| `cancelled` | Підписку скасовано або invalidated. |
| `failed` | Активація не відбулась. |

## 15.5. Lifecycle

```text
none/free -> pending -> active -> expired
                     -> failed
                     -> cancelled
```

## 15.6. Access Rule

Paid access відкривається тільки якщо:

```text
subscription.status = active
AND current_time < expires_at
AND related payment is credited
```

`pending` не відкриває paid access.

## 15.7. Expiration Rule

Після expiration:

* paid entitlements закриваються;
* користувач повертається до Free access;
* навчальні дані не видаляються;
* subscription history зберігається.

---

## 16. Payments

## 16.1. Purpose

`payments` зберігає платіжні операції Telegram Stars і idempotent credit state.

## 16.2. Required Fields

| Field | Required | Meaning |
|---|---:|---|
| `id` | Yes | Internal payment ID. |
| `user_id` | Yes | Користувач. |
| `plan` | Yes | План, який купується. |
| `amount` | Yes | Сума. |
| `currency` | Yes | Stars unit або валюта provider. |
| `provider` | Yes | `telegram_stars` для Release 1. |
| `provider_payment_id` | No | Provider payment ID. |
| `provider_reference` | No | Provider invoice або payload reference. |
| `status` | Yes | Статус платежу. |
| `idempotency_key` | Yes | Ключ зарахування. |
| `created_at` | Yes | Час створення. |
| `paid_at` | No | Час підтвердження оплати. |
| `credited_at` | No | Час зарахування доступу. |
| `failed_at` | No | Час failure. |
| `cancelled_at` | No | Час cancellation. |

## 16.3. Statuses

| Status | Meaning |
|---|---|
| `created` | Payment record створено перед invoice. |
| `pending` | Очікується provider confirmation. |
| `paid` | Provider підтвердив оплату. |
| `credited` | Доступ зараховано. |
| `failed` | Платіж неуспішний. |
| `cancelled` | Платіж скасовано. |

## 16.4. Lifecycle

```text
created -> pending -> paid -> credited
                  -> failed
                  -> cancelled
```

## 16.5. Idempotent Credit Rule

Formal invariant:

```text
one provider_payment_id -> at most one credited subscription period
```

Payment credit flow:

1. Отримати provider event.
2. Знайти Payment за provider reference або idempotency key.
3. Перевірити user ownership.
4. Перевірити expected plan and amount.
5. Перевірити current payment status.
6. Якщо вже `credited`, не створювати нову підписку.
7. Якщо `paid`, створити або активувати Subscription.
8. Перевести Payment у `credited`.
9. Записати analytics/audit event.

## 16.6. Safety Rules

* Payment failure не відкриває доступ.
* Duplicate provider event не зараховує доступ двічі.
* Payment не має містити зайві персональні дані.
* Provider debug payload не показується користувачу.
* Secrets не зберігаються в `payments`.

---

## 17. Recommendations

## 17.1. Purpose

`recommendations` зберігає згенеровані next-best learning actions.

## 17.2. Required Fields

| Field | Required | Meaning |
|---|---:|---|
| `id` | Yes | Internal recommendation ID. |
| `user_id` | Yes | Користувач. |
| `level` | Yes | Active level. |
| `theme` | No | Рекомендована тема. |
| `theme_key` | No | Стабільний ключ теми. |
| `recommendation_type` | Yes | Тип рекомендації. |
| `reason_code` | Yes | Чому рекомендація створена. |
| `priority` | Yes | Пріоритет. |
| `copy_de` | Yes | User-facing текст німецькою. |
| `source_snapshot` | No | Progress/mistake/limit context. |
| `created_at` | Yes | Час створення. |
| `shown_at` | No | Час показу. |
| `acted_at` | No | Час виконання. |

## 17.3. Recommendation Types

| Type | Meaning |
|---|---|
| `practice_theme` | Тренувати конкретну тему. |
| `repeat_mistakes` | Повторити активні помилки. |
| `continue_level` | Продовжити поточний рівень. |
| `upgrade_plan` | Показати paid upgrade, якщо є навчальна причина. |

## 17.4. Invariants

* `copy_de` має бути німецькою.
* Recommendation не радить недоступну тему.
* Recommendation не обходить Daily Limit або Subscription access.
* Recommendation має бути відтворювана з `source_snapshot` або поточного state.

---

## 18. Analytics Events

## 18.1. Purpose

`analytics_events` зберігає append-only події продукту, навчання, монетизації та технічної діагностики.

## 18.2. Required Fields

| Field | Required | Meaning |
|---|---:|---|
| `id` | Yes | Internal event ID. |
| `event_name` | Yes | Назва події. |
| `user_id` | No | Користувач, якщо відомий. |
| `session_id` | No | Сесія, якщо релевантно. |
| `source` | Yes | Джерело події. |
| `metadata` | No | Мінімальний context. |
| `timestamp` | Yes | Час події. |
| `created_at` | Yes | Час запису. |

## 18.3. Required Events

Release 1 має підтримати:

* `bot_started`;
* `user_created`;
* `level_selected`;
* `theme_selected`;
* `training_started`;
* `question_answered`;
* `training_completed`;
* `result_shown`;
* `progress_opened`;
* `mistakes_opened`;
* `mistakes_repeated`;
* `daily_limit_hit`;
* `paywall_shown`;
* `payment_started`;
* `payment_succeeded`;
* `payment_failed`;
* `subscription_started`;
* `subscription_expired`;
* `quiz_api_request_failed`.

## 18.4. Append-Only Rule

Analytics Event є append-only.

Подія не має містити:

* API keys;
* payment credentials;
* raw provider secrets;
* full Authorization headers;
* зайві персональні дані;
* raw dumps API responses з чутливими полями.

---

## 19. API Error Logs

## 19.1. Purpose

`api_error_logs` зберігає технічні помилки Quiz Bank API.

## 19.2. Required Fields

| Field | Required | Meaning |
|---|---:|---|
| `id` | Yes | Internal log ID. |
| `user_id` | No | Користувач, якщо помилка сталася в user flow. |
| `session_id` | No | Сесія, якщо є. |
| `request_id` | No | Correlation ID. |
| `endpoint` | Yes | Логічний endpoint. |
| `status_code` | No | HTTP status, якщо є. |
| `error_category` | Yes | Категорія помилки. |
| `level` | No | Рівень, якщо релевантно. |
| `theme` | No | Тема, якщо релевантно. |
| `metadata` | No | Мінімальна діагностика без secrets. |
| `occurred_at` | Yes | Час помилки. |
| `created_at` | Yes | Час запису. |

## 19.3. Error Categories

| Category | Meaning |
|---|---|
| `timeout` | API не відповів у межах timeout. |
| `network_error` | DNS, TLS або connection failure. |
| `auth_error` | 401 або 403. |
| `not_found` | Item або resource не знайдено. |
| `rate_limited` | 429. |
| `server_error` | 5xx. |
| `invalid_response` | Schema або semantic validation failed. |
| `insufficient_questions` | Недостатньо питань. |
| `content_unavailable` | Item або theme inactive. |

## 19.4. Safety Rule

API error logs не мають містити:

* API key;
* raw Authorization header;
* full raw response;
* stack trace з secrets;
* Telegram payment credentials.

---

## 20. Cross-Table Integrity Rules

## 20.1. Core Relationships

```text
users
  -> training_sessions
  -> training_session_items
  -> user_answers
  -> progress_topics
  -> mistakes
  -> subscriptions
  -> payments
  -> daily_limits
  -> analytics_events
```

## 20.2. Required Foreign Key Logic

| Relationship | Rule |
|---|---|
| `training_sessions.user_id` | Must reference existing User. |
| `training_session_items.user_id` | Must reference existing User. |
| `training_session_items.session_id` | Must reference existing Training Session. |
| `training_session_items.question_reference_id` | Must reference existing Question Reference. |
| `user_answers.user_id` | Must reference existing User. |
| `user_answers.session_id` | Must reference existing Training Session. |
| `user_answers.training_session_item_id` | Must reference existing Training Session Item. |
| `user_answers.question_reference_id` | Must reference existing Question Reference. |
| `progress_topics.user_id` | Must reference existing User. |
| `mistakes.user_id` | Must reference existing User. |
| `mistakes.question_reference_id` | Must reference existing Question Reference. |
| `subscriptions.user_id` | Must reference existing User. |
| `payments.user_id` | Must reference existing User. |
| `daily_limits.user_id` | Must reference existing User. |

## 20.3. Deletion Rule

Release 1 не має hard-delete навчальні дані у звичайному product flow.

Append-only або historical records зберігаються для:

* Training Session Items;
* User Answers;
* Progress History;
* Mistake History;
* Payments;
* Subscription History;
* Analytics Events;
* API Error Logs.

---

## 21. Transaction Rules

## 21.1. Question Shown Transaction

Question shown write має бути atomic.

Minimum atomic group:

```text
Training Session Item status
Daily Limit charge
Training Session shown_questions_count
Analytics Event
```

Якщо це transaction не завершився, питання не вважається виданим.

## 21.2. Answer Transaction

Accepted answer write має бути atomic.

Minimum atomic group:

```text
User Answer
Training Session counters
Training Session Item answered status
Progress Topic update
Mistake update if wrong
Progress History
Analytics Event
```

Якщо atomic group не може бути завершена, система не має частково видавати прогрес як підтверджений.

## 21.3. Payment Credit Transaction

Payment credit має бути atomic.

Minimum atomic group:

```text
Payment status update
Subscription activation
User subscription summary update
Analytics Event
```

Duplicate payment event має завершуватись idempotent success без повторного credit.

## 21.4. Progress Recalculation Transaction

Progress recalculation має:

* читати accepted User Answers;
* читати active/resolved Mistakes;
* оновити Progress Topic;
* записати Progress History;
* не видаляти стару історію.

---

## 22. Data Retention Rules

## 22.1. After Subscription Expiration

Після завершення Plus або Pro зберігаються:

* User;
* Training Sessions;
* Training Session Items;
* User Answers;
* Progress Topics;
* Progress History;
* Mistakes;
* Mistake History;
* Recommendations history;
* Payments;
* Subscription history;
* Analytics Events.

Expiration змінює access, а не навчальну історію.

## 22.2. Content Changes

Якщо Quiz Bank змінює питання:

* `item_id` лишається історичним reference;
* snapshots зберігають сенс минулих відповідей;
* нові відповіді використовують актуальну версію;
* content version mismatch може бути записаний у diagnostics.

---

## 23. Status Registry

## 23.1. Training Session Statuses

```text
created
active
completed
abandoned
failed
```

## 23.2. Training Session Item Statuses

```text
prepared
shown
answered
skipped
invalid
```

## 23.3. Topic Statuses

```text
new
weak
learning
stable
strong
```

## 23.4. Mistake Statuses

```text
new
repeated
improved
resolved
```

## 23.5. Subscription Statuses

```text
pending
active
expired
cancelled
failed
```

## 23.6. Payment Statuses

```text
created
pending
paid
credited
failed
cancelled
```

## 23.7. Coverage Statuses

```text
known
unknown
```

---

## 24. Data Quality Tests

Release 1 data layer має підтримати перевірки:

| Test | Expected Rule |
|---|---|
| Question shown | Creates or updates Training Session Item and charges Daily Limit once. |
| Duplicate Telegram update | Не створює другий User Answer. |
| Duplicate payment event | Не створює другу paid subscription. |
| API failure before question shown | Не списує Daily Limit. |
| Wrong answer | Створює або оновлює Mistake. |
| Correct mistake review answer | Не закриває Mistake після одного repeat. |
| Subscription expiration | Не видаляє навчальні дані. |
| Unknown availability count | Coverage becomes `unknown`. |
| Progress update | Creates Progress History. |
| Mistake update | Creates Mistake History. |
| Analytics write | Does not contain secrets. |

---

## 25. Acceptance Criteria

Data Standard виконаний для Release 1, якщо:

1. Усі core tables мають визначені поля.
2. Усі статуси мають явний registry.
3. Реально показане питання фіксується в Training Session Item.
4. User Answer зберігається тільки після реально показаного питання.
5. Duplicate answer не змінює progress вдруге.
6. Daily Limit списується тільки за показане питання.
7. Wrong answer створює або оновлює Mistake.
8. Mistake не закривається після однієї правильної відповіді.
9. Mistake lifecycle має append-only history.
10. Progress Topic оновлюється після accepted answer.
11. Progress changes записуються в Progress History.
12. Paid access відкривається тільки після credited Payment.
13. Duplicate payment event не зараховує доступ двічі.
14. Subscription expiration не видаляє навчальні дані.
15. Quiz Bank content не дублюється як локальний банк.
16. Secrets не зберігаються в analytics, logs або payment debug fields.

---

## 26. Non-Goals

Цей документ не визначає:

* конкретну SQL dialect;
* ORM models;
* migrations;
* indexes у фізичній БД;
* database hosting;
* backup policy;
* privacy deletion workflow;
* data warehouse schema;
* BI dashboard layout.

Ці рішення мають бути прийняті окремо після вибору технічного стеку.

---

## 27. Data Invariants

1. User is the root owner of learning state.
2. Quiz Bank remains the canonical source of question content.
3. User Answer is the atomic learning fact.
4. Accepted answer updates progress exactly once.
5. Wrong answer creates or updates mistake state.
6. Mistake resolution requires repeated evidence across days.
7. Progress Topic is current state; Progress History is evidence.
8. Payment is credited at most once.
9. Subscription expiration changes access, not learning history.
10. Daily Limit is charged only for shown questions.
11. API failure never creates fake learning data.
12. Append-only records are not rewritten to hide past state.
