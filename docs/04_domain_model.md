# Deutsch Trainer Bot — Domain Model

## 1. Document Purpose

Цей документ описує доменну модель **Deutsch Trainer Bot**.

Він фіксує:

* які сутності існують у системі;
* за що відповідає кожна сутність;
* які дані належать кожній сутності;
* як сутності пов’язані між собою;
* які статуси й життєві цикли мають ключові об’єкти;
* які доменні інваріанти не можна порушувати;
* які межі відповідальності має бот відносно API Quiz Bank.

Документ не є SQL-схемою, ORM-моделлю або технічним дизайном конкретної бази даних.

Його задача — дати точне спільне розуміння домену перед проєктуванням архітектури, API, схеми даних і тестів.

---

## 2. Modeling Standard

У цьому документі використовується строгий академічний стиль доменного моделювання:

* кожна сутність має одну чітку відповідальність;
* кожна сутність має власну ідентичність або чітку роль value object;
* зв’язки між сутностями описані явно;
* зовнішні джерела даних відділені від внутрішніх сутностей;
* статуси й переходи станів описані як частина домену;
* ключові правила цілісності винесені в інваріанти;
* модель не змішує продуктові правила з технічною реалізацією.

Термін “еталонний стандарт” у межах цього документа означає:

* зрозумілі визначення;
* мінімальну неоднозначність;
* перевірювані правила;
* відсутність прихованих припущень;
* придатність для подальшого перетворення в ERD, API contracts, database schema, tests і acceptance criteria.

---

## 3. Domain Boundary

## 3.1. Product Domain

Deutsch Trainer Bot відповідає за:

* користувачів;
* вибраний рівень і тему;
* навчальні сесії;
* відповіді користувача;
* прогрес;
* помилки;
* рекомендації;
* денні ліміти;
* підписки;
* платежі;
* аналітичні події;
* Telegram-інтерфейс.

## 3.2. External Content Domain

API Quiz Bank відповідає за:

* навчальні питання;
* варіанти відповідей;
* правильну відповідь;
* пояснення;
* рівень;
* тему;
* metadata для прогресу.

Deutsch Trainer Bot не дублює банк питань.

Бот зберігає тільки посилання на питання та мінімальні snapshots, потрібні для історії відповідей, прогресу, помилок і аудиту.

---

## 4. Global Domain Rules

## 4.1. Supported Levels

Підтримувані рівні:

* A1
* A2
* B1
* B2
* C1

Кожен рівень має окремий прогрес, окремі теми, окремі помилки, окремі рекомендації та окрему статистику.

## 4.2. User-Facing Language

Усі користувацькі тексти Telegram-бота мають бути німецькою мовою.

Це стосується:

* повідомлень;
* кнопок;
* результатів;
* прогресу;
* рекомендацій;
* paywall;
* оплати;
* повідомлень про помилки;
* пояснень до відповідей.

Доменна модель може бути описана українською, але будь-який user-facing copy, який зберігається або генерується системою, має бути німецькою.

## 4.3. Content Ownership

Canonical source of truth для питання — API Quiz Bank.

Deutsch Trainer Bot може зберігати:

* `item_id`;
* рівень;
* тему;
* правильну відповідь у межах конкретної відповіді користувача;
* текстове пояснення, якщо воно потрібне для історії або повторення;
* metadata snapshot для прогресу.

Deutsch Trainer Bot не має ставати основним сховищем банку питань.

## 4.4. Learning Value Rule

Кожна відповідь користувача має покращувати карту знань.

Це означає, що відповідь має впливати хоча б на один із доменних об’єктів:

* User Answer;
* Progress Topic;
* Mistake;
* Recommendation;
* Analytics Event.

---

## 5. Domain Entity Overview

| Entity | Type | Owns State | Main Purpose |
|---|---|---:|---|
| User | Aggregate root | Yes | Представляє Telegram-користувача та його навчальний стан. |
| Training Session | Entity | Yes | Групує питання й відповіді в одну навчальну сесію. |
| Question Reference | Reference entity | Limited | Посилається на питання з API Quiz Bank без дублювання банку. |
| User Answer | Entity | Yes | Фіксує конкретну відповідь користувача на конкретне питання. |
| Progress Topic | Entity | Yes | Зберігає стан знань користувача по рівню й темі. |
| Mistake | Entity | Yes | Представляє активну або закриту помилку користувача. |
| Recommendation | Entity / generated artifact | Yes | Фіксує рекомендовану наступну дію. |
| Subscription | Entity | Yes | Описує доступ користувача до платного плану. |
| Payment | Entity | Yes | Фіксує платіжну операцію і її зарахування. |
| Daily Limit | Entity | Yes | Відстежує денне використання питань за планом. |
| Analytics Event | Event record | Yes | Фіксує продуктову або технічну подію. |

---

## 6. Relationship Summary

```text
User
  ├─ 0..N Training Session
  │     └─ 1..N User Answer
  │           └─ 1 Question Reference
  ├─ 0..N Progress Topic
  ├─ 0..N Mistake
  │     └─ 1 Question Reference
  ├─ 0..N Recommendation
  ├─ 0..N Subscription
  ├─ 0..N Payment
  ├─ 0..N Daily Limit
  └─ 0..N Analytics Event

Question Reference
  └─ external canonical source: API Quiz Bank
```

## 6.1. Cardinality Rules

| Relationship | Cardinality | Rule |
|---|---:|---|
| User → Training Session | 1 to many | Один користувач може мати багато сесій. |
| Training Session → User Answer | 1 to many | Сесія містить відповіді на питання. |
| User Answer → Question Reference | many to 1 | Багато відповідей можуть посилатися на одне питання. |
| User → Progress Topic | 1 to many | Прогрес зберігається окремо для кожної пари level + theme. |
| User → Mistake | 1 to many | Користувач може мати багато активних або закритих помилок. |
| Mistake → Question Reference | many to 1 | Помилка пов’язана з конкретним питанням або item_id. |
| User → Recommendation | 1 to many | Рекомендації можуть зберігатися історично. |
| User → Subscription | 1 to many | Користувач може мати історію підписок. |
| User → Payment | 1 to many | Користувач може мати історію платежів. |
| Payment → Subscription | 0..1 to 1 | Успішний платіж може активувати одну підписку. |
| User → Daily Limit | 1 to many | Ліміт ведеться по користувачу, даті й плану. |
| User → Analytics Event | 1 to many | Події прив’язані до користувача, якщо користувач відомий. |

---

## 7. Entity Definitions

## 7.1. User

### Definition

User — це основна доменна сутність, яка представляє Telegram-користувача в системі.

User є aggregate root для навчального стану користувача.

### Responsibility

User відповідає за:

* ідентифікацію Telegram-користувача;
* активний рівень;
* активну тему;
* поточний статус підписки;
* останню активність;
* зв’язок із сесіями, прогресом, помилками, платежами й аналітикою.

### Key Attributes

| Attribute | Meaning |
|---|---|
| `id` | Внутрішній ідентифікатор користувача. |
| `telegram_user_id` | Стабільний Telegram ID. |
| `username` | Telegram username, якщо доступний. |
| `first_name` | Telegram first name, якщо доступний. |
| `language_code` | Telegram language code, якщо доступний. Не визначає мову бота. |
| `selected_level` | Активний рівень: A1, A2, B1, B2, C1. |
| `selected_theme` | Активна тема. |
| `subscription_status` | Поточний статус доступу. |
| `active_session_id` | Поточна активна сесія, якщо є. |
| `created_at` | Дата створення користувача. |
| `updated_at` | Дата останнього оновлення запису. |
| `last_active_at` | Дата останньої активності. |

### Invariants

* `telegram_user_id` має бути унікальним.
* Один Telegram-користувач не може мати два User records.
* `selected_level` може бути тільки одним із A1, A2, B1, B2, C1.
* User-facing language не визначається `language_code`; бот залишається німецькомовним.
* Видалення або завершення підписки не видаляє навчальні дані користувача.

---

## 7.2. Training Session

### Definition

Training Session — це обмежена навчальна взаємодія, у межах якої користувач відповідає на серію питань.

### Responsibility

Training Session відповідає за:

* групування питань і відповідей;
* фіксацію рівня й теми сесії;
* контроль статусу сесії;
* підрахунок результату;
* завершення навчального циклу.

### Key Attributes

| Attribute | Meaning |
|---|---|
| `id` | Ідентифікатор сесії. |
| `user_id` | Власник сесії. |
| `level` | Рівень сесії. |
| `theme` | Тема сесії. |
| `session_type` | `regular`, `mistake_review`, `recommended`. |
| `status` | Поточний статус сесії. |
| `started_at` | Час старту. |
| `completed_at` | Час завершення. |
| `total_questions` | Кількість питань у сесії. |
| `correct_answers` | Кількість правильних відповідей. |

### Statuses

| Status | Meaning |
|---|---|
| `created` | Сесія створена, але питання ще не видане. |
| `active` | Сесія триває. |
| `completed` | Користувач відповів на всі питання. |
| `abandoned` | Користувач явно або фактично вийшов із сесії. |
| `failed` | Сесія не може бути продовжена через технічну помилку. |

### Invariants

* Сесія належить рівно одному User.
* Сесія не може мати питання поза своїм `level`.
* Сесія не може мати питання поза своєю `theme`, крім спеціально визначених mixed/recommended режимів.
* `correct_answers` не може бути більшим за `total_questions`.
* Завершена сесія не має приймати нові відповіді.
* API failure не має списувати Daily Limit без виданого питання.

---

## 7.3. Question Reference

### Definition

Question Reference — це внутрішнє посилання на питання з API Quiz Bank.

Це не повна копія питання і не локальний банк питань.

### Responsibility

Question Reference відповідає за:

* стабільний зв’язок із `item_id` з API Quiz Bank;
* прив’язку відповіді або помилки до конкретного навчального item;
* збереження мінімального snapshot, потрібного для аудиту, повторення й прогресу;
* відокремлення внутрішньої історії користувача від зовнішнього content source.

### Key Attributes

| Attribute | Meaning |
|---|---|
| `item_id` | Canonical ID питання в API Quiz Bank. |
| `level` | Рівень питання. |
| `theme` | Тема питання. |
| `metadata` | Metadata для прогресу. |
| `source` | Джерело: `quiz_bank_api`. |
| `fetched_at` | Коли reference або snapshot отримано. |
| `content_version` | Версія питання, якщо API її підтримує. |

### Optional Snapshot Attributes

| Attribute | Meaning |
|---|---|
| `question_text_snapshot` | Текст питання на момент відповіді, якщо потрібен для аудиту. |
| `correct_answer_snapshot` | Правильна відповідь на момент відповіді. |
| `explanation_snapshot` | Пояснення на момент відповіді. |

### Invariants

* `item_id` має походити з API Quiz Bank.
* Question Reference не може бути створений як довільне локальне питання без зовнішнього джерела.
* Якщо API Quiz Bank змінює питання, історичні User Answer і Mistake не мають втрачати сенс.
* Snapshot зберігається тільки настільки, наскільки потрібно для історії користувача, повторення, аудиту або стабільного прогресу.

---

## 7.4. User Answer

### Definition

User Answer — це факт відповіді користувача на конкретне питання в конкретній сесії.

### Responsibility

User Answer відповідає за:

* фіксацію відповіді;
* результат правильності;
* час відповіді;
* джерело для прогресу;
* джерело для створення або оновлення помилки;
* захист від duplicate Telegram update.

### Key Attributes

| Attribute | Meaning |
|---|---|
| `id` | Ідентифікатор відповіді. |
| `user_id` | Користувач. |
| `session_id` | Навчальна сесія. |
| `item_id` | Посилання на Question Reference. |
| `level` | Рівень питання на момент відповіді. |
| `theme` | Тема питання на момент відповіді. |
| `selected_answer` | Вибрана відповідь. |
| `correct_answer` | Правильна відповідь на момент перевірки. |
| `is_correct` | Чи була відповідь правильною. |
| `response_time_ms` | Час відповіді. |
| `answered_at` | Час відповіді. |
| `telegram_update_id` | Update ID для idempotency, якщо доступний. |

### Invariants

* Один користувач може відповісти на одне питання в межах однієї сесії тільки один раз.
* Duplicate Telegram update не має створювати другий User Answer.
* User Answer не може існувати без User.
* User Answer не може існувати без Training Session.
* User Answer має посилатися на Question Reference.
* Кожна User Answer має оновити Progress Topic або бути явно відхилена як duplicate.

---

## 7.5. Progress Topic

### Definition

Progress Topic — це агрегований стан знань користувача по конкретній парі `level + theme`.

### Responsibility

Progress Topic відповідає за:

* accuracy;
* coverage;
* stability;
* weakness;
* recency;
* topic status;
* основу для рекомендацій.

### Key Attributes

| Attribute | Meaning |
|---|---|
| `id` | Ідентифікатор прогресу. |
| `user_id` | Користувач. |
| `level` | Рівень. |
| `theme` | Тема. |
| `accuracy_score` | Частка правильних відповідей. |
| `coverage_score` | Частка унікальних пройдених питань. |
| `stability_score` | Оцінка стабільності через повторення в різні дні. |
| `weakness_score` | Оцінка слабкості теми. |
| `topic_status` | Статус теми. |
| `answered_count` | Загальна кількість відповідей по темі. |
| `correct_count` | Кількість правильних відповідей. |
| `unique_items_seen` | Кількість унікальних item_id. |
| `last_practiced_at` | Останнє тренування теми. |
| `updated_at` | Останнє оновлення прогресу. |

### Topic Statuses

| Status | Meaning |
|---|---|
| `new` | Недостатньо даних. |
| `weak` | Низька accuracy або повторні помилки. |
| `learning` | Є прогрес, але тема ще нестабільна. |
| `stable` | Користувач стабільно відповідає правильно. |
| `strong` | Висока accuracy, coverage і stability. |

### Score Definitions

| Score | Base Meaning |
|---|---|
| `accuracy_score` | `correct_answers / total_answers`. |
| `coverage_score` | `answered_unique_items / available_items`. |
| `stability_score` | Правильні повторення в різні дні та відсутність повернення до старих помилок. |
| `weakness_score` | Вплив неправильних відповідей, повторних помилок і низької стабільності. |

### Invariants

* Для одного User не має бути двох Progress Topic з однаковими `level + theme`.
* Progress Topic не може змішувати різні рівні.
* Висока accuracy без coverage не означає сильну тему.
* Тема не може бути `strong`, якщо coverage або stability недостатні.
* `last_practiced_at` оновлюється після виданої та обробленої відповіді.

---

## 7.6. Mistake

### Definition

Mistake — це збережена неправильна відповідь або нестабільне знання користувача, яке потребує повторення.

### Responsibility

Mistake відповідає за:

* збереження неправильної відповіді;
* підрахунок повторних помилок;
* відстеження покращення;
* контроль resolution;
* формування mistake review session.

### Key Attributes

| Attribute | Meaning |
|---|---|
| `id` | Ідентифікатор помилки. |
| `user_id` | Користувач. |
| `item_id` | Question Reference. |
| `level` | Рівень. |
| `theme` | Тема. |
| `wrong_answer` | Остання неправильна відповідь. |
| `correct_answer` | Правильна відповідь. |
| `mistake_count` | Кількість помилок по цьому item. |
| `successful_repeats_count` | Кількість успішних повторень. |
| `status` | Статус помилки. |
| `first_mistake_at` | Перша помилка. |
| `last_mistake_at` | Остання помилка. |
| `last_repeated_at` | Останнє повторення. |
| `resolved_at` | Час закриття помилки. |

### Statuses

| Status | Meaning |
|---|---|
| `new` | Помилка створена вперше. |
| `repeated` | Помилка повторювалася або стала повторною. |
| `improved` | Користувач відповів правильно під час повторення, але помилка ще не закрита. |
| `resolved` | Помилка закрита після кількох правильних повторень у різні дні. |

### Invariants

* Помилка не закривається після однієї правильної відповіді.
* Повторна неправильна відповідь збільшує `mistake_count`.
* Correct repeat може перевести `new` або `repeated` у `improved`.
* `resolved` вимагає кількох правильних повторень у різні дні.
* Resolved mistake може знову відкритися, якщо користувач повторно помиляється.
* Mistake має впливати на Progress Topic і Recommendation.

---

## 7.7. Recommendation

### Definition

Recommendation — це запропонована наступна навчальна дія для користувача.

### Responsibility

Recommendation відповідає за:

* вибір теми або дії для тренування;
* пояснення причини рекомендації;
* персоналізацію на основі прогресу, помилок, recency і плану;
* показ користувачу короткої наступної дії.

### Key Attributes

| Attribute | Meaning |
|---|---|
| `id` | Ідентифікатор рекомендації. |
| `user_id` | Користувач. |
| `level` | Активний рівень. |
| `theme` | Рекомендована тема, якщо є. |
| `recommendation_type` | `practice_theme`, `repeat_mistakes`, `continue_level`, `upgrade_plan`. |
| `reason_code` | Причина рекомендації. |
| `priority` | Пріоритет. |
| `copy_de` | User-facing текст німецькою. |
| `created_at` | Час створення. |
| `shown_at` | Час показу. |
| `acted_at` | Час виконання користувачем. |

### Inputs

Recommendation використовує:

* selected_level;
* selected_theme;
* Progress Topic;
* Mistake;
* Daily Limit;
* Subscription;
* recency;
* кількість доступних питань.

### Invariants

* User-facing recommendation copy має бути німецькою.
* Рекомендація не має радити тему без доступних питань.
* Рекомендація має бути короткою.
* Якщо даних недостатньо, рекомендація має чесно це відображати.
* Recommendation не має обходити план доступу або Daily Limit.

---

## 7.8. Subscription

### Definition

Subscription — це право користувача на доступ до платних можливостей у межах плану.

### Responsibility

Subscription відповідає за:

* план користувача;
* статус доступу;
* період дії;
* зв’язок із платежем;
* правила доступу до функцій.

### Key Attributes

| Attribute | Meaning |
|---|---|
| `id` | Ідентифікатор підписки. |
| `user_id` | Користувач. |
| `plan` | `Free`, `Plus`, `Pro`. |
| `status` | Статус підписки. |
| `started_at` | Початок дії. |
| `expires_at` | Завершення дії. |
| `provider` | Провайдер. |
| `provider_reference` | Зовнішній reference. |
| `created_at` | Час створення. |
| `updated_at` | Час оновлення. |

### Plans

| Plan | Meaning |
|---|---|
| `Free` | Базовий доступ з денним лімітом. |
| `Plus` | Основний платний план з повним прогресом і повторенням помилок. |
| `Pro` | Розширений план для активних користувачів. |

### Statuses

| Status | Meaning |
|---|---|
| `active` | Доступ активний. |
| `expired` | Період дії завершився. |
| `cancelled` | Підписку скасовано. |
| `pending` | Очікується підтвердження платежу або активації. |

### Invariants

* Платний доступ відкривається тільки після підтвердженого платежу.
* Завершення підписки не видаляє навчальні дані.
* Якщо платна підписка завершилась, користувач повертається до Free-доступу.
* Active Subscription має мати зрозумілий plan access rule.
* Одночасні активні paid subscriptions для одного користувача мають бути або заборонені, або явно врегульовані policy.

---

## 7.9. Payment

### Definition

Payment — це платіжна операція, яка може активувати підписку або разову покупку.

### Responsibility

Payment відповідає за:

* створення платіжної операції;
* зв’язок із Telegram Stars;
* перевірку успішного платежу;
* idempotency;
* audit log;
* активацію підписки після підтвердження.

### Key Attributes

| Attribute | Meaning |
|---|---|
| `id` | Ідентифікатор платежу. |
| `user_id` | Користувач. |
| `plan` | План, який купується. |
| `amount` | Сума. |
| `currency` | Валюта або Telegram Stars unit. |
| `provider` | `telegram_stars`. |
| `provider_payment_id` | Зовнішній ID платежу. |
| `status` | Статус платежу. |
| `idempotency_key` | Ключ захисту від повторного зарахування. |
| `created_at` | Час створення. |
| `paid_at` | Час успішної оплати. |
| `credited_at` | Час зарахування доступу. |

### Statuses

| Status | Meaning |
|---|---|
| `created` | Платіж створено. |
| `pending` | Очікується підтвердження. |
| `paid` | Провайдер підтвердив оплату. |
| `credited` | Доступ зараховано. |
| `failed` | Платіж неуспішний. |
| `cancelled` | Користувач або провайдер скасував платіж. |

### Invariants

* Один provider payment не може бути зарахований двічі.
* Subscription не активується без підтвердженого Payment.
* Payment failure не відкриває платний доступ.
* Усі платіжні події мають бути придатні для audit.
* Payment не має містити зайві персональні дані.

---

## 7.10. Daily Limit

### Definition

Daily Limit — це стан використання денного ліміту питань користувачем.

### Responsibility

Daily Limit відповідає за:

* денну квоту питань;
* використання питань;
* reset за timezone Europe/Berlin;
* захист Free/Plus/Pro limits;
* paywall trigger після завершення ліміту.

### Key Attributes

| Attribute | Meaning |
|---|---|
| `id` | Ідентифікатор ліміту. |
| `user_id` | Користувач. |
| `plan` | План, за яким рахувався ліміт. |
| `limit_date` | Дата ліміту у timezone Europe/Berlin. |
| `timezone` | `Europe/Berlin`. |
| `question_limit` | Максимальна кількість питань. |
| `questions_used` | Кількість реально виданих питань. |
| `reset_at` | Наступний reset. |
| `created_at` | Час створення запису. |
| `updated_at` | Час оновлення. |

### Invariants

* Ліміт списується тільки після фактичної видачі питання.
* API failure не списує ліміт.
* Duplicate Telegram update не списує ліміт вдруге.
* `questions_used` не може перевищувати `question_limit`, крім явно визначених paid overflow rules.
* Reset відбувається за Europe/Berlin day.
* Daily Limit має враховувати активний Subscription plan.

---

## 7.11. Analytics Event

### Definition

Analytics Event — це запис про продуктову, навчальну, платіжну або технічну подію.

### Responsibility

Analytics Event відповідає за:

* activation metrics;
* retention metrics;
* learning value metrics;
* monetization metrics;
* operational diagnostics;
* audit trail для важливих дій.

### Key Attributes

| Attribute | Meaning |
|---|---|
| `id` | Ідентифікатор події. |
| `event_name` | Назва події. |
| `user_id` | Користувач, якщо відомий. |
| `timestamp` | Час події. |
| `source` | Джерело події. |
| `metadata` | Мінімальний контекст події. |

### Core Event Names

| Event | Meaning |
|---|---|
| `bot_started` | Користувач відкрив бот. |
| `user_created` | Створено нового користувача. |
| `level_selected` | Користувач вибрав рівень. |
| `theme_selected` | Користувач вибрав тему. |
| `training_started` | Почалась сесія. |
| `question_answered` | Користувач відповів на питання. |
| `training_completed` | Сесія завершена. |
| `result_shown` | Результат показаний. |
| `progress_opened` | Прогрес відкритий. |
| `mistakes_opened` | Журнал помилок відкритий. |
| `mistakes_repeated` | Користувач повторював помилки. |
| `daily_limit_hit` | Денний ліміт досягнуто. |
| `paywall_shown` | Paywall показаний. |
| `paywall_clicked` | Користувач натиснув paywall action. |
| `payment_started` | Почато оплату. |
| `payment_succeeded` | Оплата успішна. |
| `payment_failed` | Оплата неуспішна. |
| `subscription_started` | Підписка активована. |
| `subscription_expired` | Підписка завершилась. |

### Invariants

* Analytics Event не має містити зайві персональні дані.
* Payment-related events не мають містити секрети або повні credentials.
* Analytics Event має бути append-only.
* Відсутність analytics не має ламати навчальний flow користувача.

---

## 8. Cross-Entity Domain Rules

## 8.1. Answer Processing Rule

Коли користувач відповідає на питання, система має виконати доменні дії в узгодженому порядку:

1. Перевірити, що сесія активна.
2. Перевірити, що відповідь не duplicate.
3. Створити User Answer.
4. Оновити Training Session counters.
5. Оновити Progress Topic.
6. Якщо відповідь неправильна, створити або оновити Mistake.
7. Оновити Daily Limit, якщо питання було реально видане.
8. Записати Analytics Event.

## 8.2. Mistake Review Rule

Під час повторення помилок:

* сесія має мати `session_type = mistake_review`;
* питання беруться з активних Mistake records;
* правильна відповідь не закриває Mistake одразу;
* кілька правильних повторень у різні дні можуть перевести Mistake у `resolved`;
* результат повторення має впливати на Progress Topic stability.

## 8.3. Subscription Access Rule

Перед доступом до платної функції система перевіряє:

1. User.
2. Active Subscription.
3. Plan access rules.
4. Daily Limit.
5. Feature availability.

Якщо доступу немає, система може показати paywall тільки після того, як користувач уже побачив продуктову користь.

## 8.4. Payment Credit Rule

Після успішного платежу:

1. Payment переходить у `paid`.
2. Система перевіряє idempotency.
3. Якщо платіж ще не зарахований, створюється або активується Subscription.
4. Payment переходить у `credited`.
5. Записуються `payment_succeeded` і `subscription_started`.

Один платіж не може створити більше одного зарахування доступу.

## 8.5. Recommendation Rule

Recommendation має будуватися з:

* слабких тем;
* старих помилок;
* давно не повторених тем;
* активного рівня;
* активного плану;
* доступного денного ліміту;
* доступності питань в API Quiz Bank.

Рекомендація не має радити користувачу дію, яку він не може виконати.

---

## 9. Lifecycle Summaries

## 9.1. Training Session Lifecycle

```text
created → active → completed
                 ↘ abandoned
                 ↘ failed
```

## 9.2. Mistake Lifecycle

```text
new → repeated → improved → resolved
 ↑        ↓          ↓
 └────────┴──────────┘
```

Якщо користувач знову помиляється після `improved` або `resolved`, помилка може повернутися в активний стан.

## 9.3. Payment Lifecycle

```text
created → pending → paid → credited
        ↘ failed
        ↘ cancelled
```

## 9.4. Subscription Lifecycle

```text
pending → active → expired
              ↘ cancelled
```

## 9.5. Progress Topic Lifecycle

```text
new → weak → learning → stable → strong
      ↑        ↓          ↓        ↓
      └────────┴──────────┴────────┘
```

Progress Topic може деградувати, якщо користувач повертається до старих помилок.

---

## 10. Domain Integrity Checklist

Перед реалізацією або зміною доменної логіки потрібно перевірити:

* чи не дублюється Quiz Bank у боті;
* чи кожна відповідь створює User Answer або коректно відхиляється як duplicate;
* чи Progress Topic оновлюється по правильному `level + theme`;
* чи Mistake не закривається після одного правильного повторення;
* чи Daily Limit не списується після API failure;
* чи Payment не може бути зарахований двічі;
* чи Subscription expiration не видаляє навчальні дані;
* чи Analytics Event не містить зайві персональні дані;
* чи user-facing copy лишається німецькою;
* чи рівні A1, A2, B1, B2, C1 підтримані всюди однаково.

---

## 11. Release 1 Domain Completeness

Для Release 1 доменна модель вважається достатньою, якщо реалізовані такі об’єкти:

1. User.
2. Training Session.
3. Question Reference.
4. User Answer.
5. Progress Topic.
6. Mistake.
7. Recommendation.
8. Subscription.
9. Payment.
10. Daily Limit.
11. Analytics Event.

І якщо виконуються такі доменні правила:

* основний flow працює від `/start` до результату;
* питання приходять з API Quiz Bank;
* відповіді зберігаються;
* прогрес рахується окремо по рівнях і темах;
* помилки зберігаються й повторюються;
* рекомендації базуються на реальних даних;
* Free limit працює за Europe/Berlin day;
* Plus / Pro access перевіряється перед платними функціями;
* Telegram Stars payment має idempotent credit;
* аналітичні події записуються;
* user-facing bot interface повністю німецькомовний.

---

## 12. Final Domain Statement

Deutsch Trainer Bot має домен, побудований навколо персональної карти знань користувача.

Центральний об’єкт — **User**, але головна навчальна цінність виникає через зв’язок:

```text
User → User Answer → Progress Topic → Mistake → Recommendation
```

Платна модель додає доступ і ліміти через:

```text
User → Daily Limit → Subscription → Payment
```

Аналітика фіксує, чи цей навчальний і бізнес-цикл реально працює:

```text
User → Analytics Event
```

Головний доменний принцип:

> Кожна відповідь користувача має або покращити карту знань, або створити точний сигнал для повторення, прогресу чи рекомендації.
