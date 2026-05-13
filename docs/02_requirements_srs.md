# Deutsch Trainer Bot — Software Requirements Specification

## 1. Document Purpose

Цей документ описує вимоги до **Deutsch Trainer Bot**.

Він фіксує:

* що система має робити;
* які дані має зберігати;
* як має працювати Telegram-бот;
* як має рахуватися прогрес;
* як мають працювати помилки;
* як мають працювати ліміти й підписки;
* як бот має працювати з API Quiz Bank;
* які критерії готовності потрібні для Release 1.

---

## 2. Product Scope

**Deutsch Trainer Bot** — це Telegram-бот для щоденного тренування німецької мови.

Release 1 має включати:

1. Реєстрацію користувача через Telegram.
2. Вибір рівня.
3. Вибір теми.
4. Короткі тренувальні сесії.
5. Отримання питань з API Quiz Bank.
6. Збереження відповідей.
7. Підрахунок результату сесії.
8. Прогрес по темах.
9. Журнал помилок.
10. Повторення помилок.
11. Щоденну рекомендацію.
12. Free-ліміти.
13. Plus / Pro-підписки.
14. Telegram Stars-платежі.
15. Базову аналітику.
16. Базову адмінську статистику.
17. Повністю німецькомовний користувацький інтерфейс.

---

## 3. Requirement Levels

У документі використовуються такі рівні важливості:

* **MUST** — обов’язково для Release 1.
* **SHOULD** — бажано для Release 1, але не блокує базовий запуск.
* **LATER** — може бути реалізовано після Release 1.

---

## 4. Core Actors

## 4.1. Learner

Основний користувач бота.

Може:

* запускати бот;
* вибирати рівень;
* вибирати тему;
* проходити сесії;
* дивитися прогрес;
* повторювати помилки;
* купувати підписку.

## 4.2. Admin

Власник або оператор продукту.

Може:

* дивитися базову статистику;
* бачити помилки API;
* бачити платіжні події;
* перевіряти активність користувачів;
* контролювати стабільність системи.

## 4.3. API Quiz Bank

Зовнішнє джерело навчального контенту.

Віддає:

* питання;
* рівень;
* тему;
* відповіді;
* правильну відповідь;
* пояснення;
* metadata.

---

## 5. Functional Requirements

# 5.1. User Registration

## FR-001 — Automatic User Creation

**MUST**

Коли користувач вперше запускає бот, система має автоматично створити запис користувача.

Система має зберегти:

* Telegram user ID;
* username, якщо доступний;
* first_name, якщо доступний;
* language_code, якщо доступний;
* дату створення;
* дату останньої активності.

## FR-002 — Returning User Recognition

**MUST**

Якщо користувач уже існує, бот не має створювати дубль.

Система має оновити:

* last_active_at;
* поточний стан користувача;
* останній відкритий екран, якщо потрібно.

## FR-003 — User State

**MUST**

Система має зберігати поточний навчальний стан користувача:

* selected_level;
* selected_theme;
* active_session_id;
* subscription_status;
* daily_limit_state.

---

# 5.2. Onboarding

## FR-010 — First Start Message

**MUST**

Після першого запуску бот має коротко пояснити користувачу цінність продукту.

Повідомлення має бути німецькою мовою і відповідати змісту:

> Ich helfe dir, Deutsch zu üben, deinen Fortschritt zu sehen und Fehler zu wiederholen.

## FR-011 — Level Selection During Onboarding

**MUST**

Після першого запуску бот має запропонувати вибрати рівень:

* A1
* A2
* B1
* B2
* C1

Текст і кнопки мають бути німецькою мовою.

## FR-012 — Default Theme Handling

**MUST**

Після вибору рівня система має дозволити користувачу:

* вибрати тему вручну;
* або почати тренування з рекомендованої теми.

---

# 5.3. Home Screen

## FR-020 — Main Home Screen

**MUST**

Головний екран має містити три основні дії:

1. **▶️ Üben**
2. **🎯 Niveau & Thema**
3. **📊 Mein Fortschritt**

## FR-021 — Home Screen Simplicity

**MUST**

Головний екран не має містити зайвих дій, які не потрібні для основного навчального циклу.

## FR-022 — Return to Home

**MUST**

Користувач має мати можливість повернутися на головний екран з основних розділів.

---

# 5.4. Level Management

## FR-030 — Select Level

**MUST**

Користувач має мати можливість вибрати рівень:

* A1
* A2
* B1
* B2
* C1

## FR-031 — Change Level

**MUST**

Користувач має мати можливість змінити рівень у будь-який момент через розділ **🎯 Niveau & Thema**.

## FR-032 — Level-Specific Progress

**MUST**

Прогрес має рахуватися окремо для кожного рівня.

Приклад:

* A1 progress;
* A2 progress;
* B1 progress;
* B2 progress;
* C1 progress.

---

# 5.5. Theme Management

## FR-040 — Select Theme

**MUST**

Користувач має мати можливість вибрати тему.

Базові теми Release 1:

* Artikel;
* Verben;
* Fälle;
* Wortschatz;
* Alltag;
* Prüfung.

## FR-041 — Change Theme

**MUST**

Користувач має мати можливість змінити тему через розділ **🎯 Niveau & Thema**.

## FR-042 — Theme Availability

**MUST**

Бот має показувати тільки ті теми, для яких є доступні питання в API Quiz Bank.

## FR-043 — Empty Theme Handling

**MUST**

Якщо для вибраної теми немає доступних питань, бот має показати зрозуміле повідомлення і запропонувати іншу тему.

---

# 5.6. Training Session

## FR-050 — Start Training Session

**MUST**

Користувач має мати можливість почати тренувальну сесію через кнопку **▶️ Üben**.

## FR-051 — Session Size

**MUST**

Базова сесія має містити 5–10 питань.

Точна кількість має бути налаштовуваною через конфігурацію.

## FR-052 — Question Source

**MUST**

Питання для сесії мають надходити з API Quiz Bank.

## FR-053 — Question Filtering

**MUST**

Питання мають відповідати:

* вибраному рівню;
* вибраній темі;
* доступному плану користувача;
* денному ліміту користувача.

## FR-054 — Question Display

**MUST**

Кожне питання має показувати:

* текст питання;
* варіанти відповідей;
* кнопки відповідей.

## FR-055 — One Answer Per Question

**MUST**

Користувач може дати тільки одну відповідь на одне питання в межах сесії.

## FR-056 — Save Every Answer

**MUST**

Кожна відповідь має бути збережена.

Система має зберегти:

* user_id;
* session_id;
* item_id;
* selected_answer;
* correct_answer;
* is_correct;
* response_time;
* answered_at.

## FR-057 — Complete Session

**MUST**

Сесія завершується після відповіді на всі питання або після явного виходу користувача.

## FR-058 — Session Result

**MUST**

Після завершення сесії бот має показати:

* кількість правильних відповідей;
* загальну кількість питань;
* відсоток результату;
* слабку тему;
* кількість нових помилок;
* рекомендацію наступної дії.

---

# 5.7. Result Screen

## FR-060 — Result Summary

**MUST**

Після кожної сесії бот має показати короткий результат.

Приклад:

```text
Ergebnis: 8/10
Schwachstelle: Artikel
Neue Fehler: 2
```

## FR-061 — Result Actions

**MUST**

Після результату мають бути доступні дії:

* **🔁 Fehler wiederholen**
* **▶️ Noch eine Übung**
* **📊 Mein Fortschritt**

## FR-062 — No Long Explanation

**MUST**

Екран результату має бути коротким і зрозумілим.

---

# 5.8. Progress System

## FR-070 — Progress Per Topic

**MUST**

Система має рахувати прогрес окремо по кожній темі.

## FR-071 — Progress Per Level

**MUST**

Система має рахувати загальний прогрес по кожному рівню.

## FR-072 — Accuracy Score

**MUST**

Система має рахувати accuracy:

```text
correct_answers / total_answers
```

## FR-073 — Coverage Score

**MUST**

Система має рахувати coverage:

```text
answered_unique_items / available_items
```

## FR-074 — Stability Score

**MUST**

Система має оцінювати стабільність знань через повторні відповіді в різні дні.

## FR-075 — Weakness Detection

**MUST**

Система має визначати слабкі теми на основі:

* неправильних відповідей;
* повторних помилок;
* низької accuracy;
* низької stability.

## FR-076 — Recency Tracking

**MUST**

Система має зберігати, коли користувач востаннє тренував тему.

## FR-077 — Topic Status

**MUST**

Кожна тема має мати статус:

* new;
* weak;
* learning;
* stable;
* strong.

## FR-078 — Progress Screen

**MUST**

Екран прогресу має показувати:

* активний рівень;
* загальний прогрес;
* сильні теми;
* слабкі теми;
* рекомендацію на сьогодні.

---

# 5.9. Mistake System

## FR-090 — Mistake Creation

**MUST**

Якщо користувач відповів неправильно, система має створити або оновити запис помилки.

## FR-091 — Mistake Journal

**MUST**

Система має зберігати журнал помилок.

Для кожної помилки:

* user_id;
* item_id;
* level;
* theme;
* wrong_answer;
* correct_answer;
* mistake_count;
* last_mistake_at;
* status.

## FR-092 — Mistake Status

**MUST**

Помилка має мати статус:

* new;
* repeated;
* improved;
* resolved.

## FR-093 — Repeat Mistakes

**MUST**

Користувач має мати можливість пройти окрему сесію з власних помилок.

## FR-094 — Mistake Resolution

**MUST**

Помилка не має закриватися після однієї правильної відповіді.

Базове правило:

* одна правильна повторна відповідь → improved;
* кілька правильних відповідей у різні дні → resolved.

## FR-095 — Mistake History

**SHOULD**

Система має зберігати історію повторень помилки.

---

# 5.10. Daily Recommendation

## FR-100 — Generate Daily Recommendation

**MUST**

Система має формувати рекомендацію для користувача.

Рекомендація має відповідати на питання:

> Was soll ich jetzt üben?

## FR-101 — Recommendation Inputs

**MUST**

Рекомендація має враховувати:

* вибраний рівень;
* вибрану тему;
* слабкі теми;
* старі помилки;
* давно не повторені теми;
* денний ліміт;
* активний план користувача.

## FR-102 — Recommendation Output

**MUST**

Рекомендація має бути короткою.

Приклад:

```text
Heute solltest du Dativ und Artikel wiederholen.
```

---

# 5.11. Free Limits

## FR-110 — Daily Free Limit

**MUST**

Free-користувач має мати денний ліміт питань.

Ліміт має бути налаштовуваним через конфігурацію.

## FR-111 — Limit Reset

**MUST**

Денний ліміт має оновлюватися один раз на день.

Базова timezone: Europe/Berlin.

## FR-112 — Limit Check Before Question

**MUST**

Система має перевіряти ліміт перед видачею питання.

## FR-113 — No Limit Charge on Failed API Request

**MUST**

Якщо питання не було видано через помилку API, ліміт не має списуватися.

## FR-114 — Daily Limit Hit Message

**MUST**

Коли ліміт завершено, бот має показати зрозуміле повідомлення і запропонувати платний план.

---

# 5.12. Subscription System

## FR-120 — Subscription Plans

**MUST**

Система має підтримувати плани:

* Free;
* Plus;
* Pro.

## FR-121 — Plan Access Rules

**MUST**

Кожен план має мати чіткі правила доступу:

* daily_question_limit;
* progress_detail_level;
* mistake_repeat_access;
* recommendation_access;
* advanced_stats_access.

## FR-122 — Active Subscription Check

**MUST**

Перед платною функцією система має перевірити статус підписки.

## FR-123 — Subscription Expiration

**MUST**

Після завершення підписки користувач має повернутися до Free-доступу.

## FR-124 — No Data Loss After Expiration

**MUST**

Після завершення підписки навчальні дані користувача не мають видалятися.

Платний доступ закривається, але дані зберігаються.

---

# 5.13. Payments

## FR-130 — Telegram Stars Payment

**MUST**

Система має підтримувати оплату через Telegram Stars.

## FR-131 — Payment Creation

**MUST**

Система має створювати платіжну операцію перед оплатою.

## FR-132 — Payment Verification

**MUST**

Система має перевіряти успішний платіж перед активацією підписки.

## FR-133 — Idempotent Payment Credit

**MUST**

Один платіж не може активувати підписку більше одного разу.

## FR-134 — Payment Failure Handling

**MUST**

Якщо платіж неуспішний, система має показати зрозуміле повідомлення і не активувати підписку.

## FR-135 — Payment Audit Log

**MUST**

Платіжні події мають логуватися для аудиту.

---

# 5.14. Paywall

## FR-140 — Paywall After Value

**MUST**

Платна пропозиція має з’являтися після того, як користувач уже побачив користь.

## FR-141 — Paywall Moments

**MUST**

Paywall може з’являтися:

* після завершення сесії;
* після виявлення слабкої теми;
* після повторної помилки;
* після досягнення денного ліміту;
* перед відкриттям повної карти прогресу.

## FR-142 — Paywall Message

**MUST**

Paywall має пояснювати користь.

Приклад:

```text
Ich habe deine Schwachstellen gefunden.
Mit Plus kannst du deinen vollständigen Fortschritt sehen und deine Fehler gezielt wiederholen.
```

---

# 5.15. API Quiz Bank Integration

## FR-150 — Fetch Questions

**MUST**

Бот має отримувати питання з API Quiz Bank.

## FR-151 — Request Filters

**MUST**

Запит до API має підтримувати фільтри:

* level;
* theme;
* count;
* exclude_seen;
* user_context, якщо потрібно.

## FR-152 — Required Question Fields

**MUST**

Кожне питання з API має містити:

* item_id;
* level;
* theme;
* question_text;
* answer_options;
* correct_answer;
* explanation;
* metadata.

## FR-153 — API Error Handling

**MUST**

Якщо API недоступний, бот має:

* показати зрозуміле повідомлення;
* не списувати ліміт;
* не ламати активну сесію;
* записати технічну помилку.

## FR-154 — Insufficient Questions Handling

**MUST**

Якщо API повернув недостатньо питань, бот має:

* або створити коротшу сесію;
* або запропонувати іншу тему;
* або показати повідомлення про нестачу питань.

Правило має бути задане в конфігурації.

---

# 5.16. Analytics

## FR-160 — Event Tracking

**MUST**

Система має записувати ключові події.

## FR-161 — Required Events

**MUST**

Release 1 має містити події:

* bot_started;
* user_created;
* level_selected;
* theme_selected;
* training_started;
* question_answered;
* training_completed;
* result_shown;
* progress_opened;
* mistakes_opened;
* mistakes_repeated;
* daily_limit_hit;
* paywall_shown;
* paywall_clicked;
* payment_started;
* payment_succeeded;
* payment_failed;
* subscription_started;
* subscription_expired.

## FR-162 — Analytics Event Fields

**MUST**

Кожна подія має містити:

* event_name;
* user_id;
* timestamp;
* source;
* metadata.

## FR-163 — No Sensitive Data in Analytics

**MUST**

Аналітичні події не мають містити зайвих персональних даних.

---

# 5.17. Admin Statistics

## FR-170 — Admin Dashboard Data

**MUST**

Адмін має бачити базові показники:

* total_users;
* active_users_today;
* training_sessions_today;
* answers_today;
* payment_count;
* active_subscriptions;
* API errors;
* payment errors.

## FR-171 — Learning Metrics for Admin

**SHOULD**

Адмін має бачити:

* популярні рівні;
* популярні теми;
* теми з найбільшою кількістю помилок;
* кількість повторень помилок.

## FR-172 — Admin Access Protection

**MUST**

Адмінська статистика має бути захищена.

---

# 5.18. German-Only User Interface

## FR-180 — German-Only Bot Interface

**MUST**

Усі користувацькі тексти Telegram-бота мають бути німецькою мовою.

Це включає:

* onboarding;
* головне меню;
* кнопки;
* вибір рівня;
* вибір теми;
* питання;
* відповіді;
* результат сесії;
* екран прогресу;
* журнал помилок;
* рекомендації;
* paywall;
* оплату;
* повідомлення про ліміти;
* повідомлення про помилки.

## FR-181 — No Ukrainian User-Facing Copy

**MUST**

Бот не має показувати український текст користувачу в основному інтерфейсі.

Українська мова може використовуватися тільки у внутрішній документації, робочих поясненнях або адміністративному контексті, якщо це окремо дозволено.

## FR-182 — German UX Copy Level

**MUST**

Німецькі тексти мають бути простими, короткими й зрозумілими для користувачів A1–C1.

Для базових екранів слід використовувати просту німецьку мову.

Приклад головного меню:

```text
Was möchtest du heute üben?

▶️ Üben
🎯 Niveau & Thema
📊 Mein Fortschritt
```

## FR-183 — German Error Messages

**MUST**

Навіть повідомлення про помилки мають бути німецькою.

Приклад:

```text
Etwas ist schiefgelaufen. Bitte versuche es noch einmal.
```

## FR-184 — German Paywall Copy

**MUST**

Paywall має бути німецькою мовою.

Приклад:

```text
Ich habe deine Schwachstellen gefunden.
Mit Plus kannst du deinen vollständigen Fortschritt sehen und deine Fehler gezielt wiederholen.
```

---

## 6. Data Requirements

# 6.1. User Data

## DR-001 — User Table

**MUST**

Система має зберігати користувача.

Поля:

* id;
* telegram_user_id;
* username;
* first_name;
* language_code;
* selected_level;
* selected_theme;
* subscription_status;
* created_at;
* updated_at;
* last_active_at.

---

# 6.2. Training Session Data

## DR-010 — Training Session Table

**MUST**

Система має зберігати навчальні сесії.

Поля:

* id;
* user_id;
* level;
* theme;
* status;
* started_at;
* completed_at;
* total_questions;
* correct_answers.

---

# 6.3. User Answer Data

## DR-020 — User Answer Table

**MUST**

Система має зберігати відповіді користувача.

Поля:

* id;
* user_id;
* session_id;
* item_id;
* level;
* theme;
* selected_answer;
* correct_answer;
* is_correct;
* response_time_ms;
* answered_at.

---

# 6.4. Progress Data

## DR-030 — Progress Topic Table

**MUST**

Система має зберігати прогрес по темах.

Поля:

* id;
* user_id;
* level;
* theme;
* accuracy_score;
* coverage_score;
* stability_score;
* weakness_score;
* topic_status;
* answered_count;
* correct_count;
* unique_items_seen;
* last_practiced_at;
* updated_at.

---

# 6.5. Mistake Data

## DR-040 — Mistake Table

**MUST**

Система має зберігати помилки.

Поля:

* id;
* user_id;
* item_id;
* level;
* theme;
* wrong_answer;
* correct_answer;
* mistake_count;
* successful_repeats_count;
* status;
* first_mistake_at;
* last_mistake_at;
* resolved_at.

---

# 6.6. Subscription Data

## DR-050 — Subscription Table

**MUST**

Система має зберігати підписки.

Поля:

* id;
* user_id;
* plan;
* status;
* started_at;
* expires_at;
* provider;
* provider_reference;
* created_at;
* updated_at.

---

# 6.7. Payment Data

## DR-060 — Payment Table

**MUST**

Система має зберігати платежі.

Поля:

* id;
* user_id;
* plan;
* amount;
* currency;
* provider;
* provider_payment_id;
* status;
* created_at;
* paid_at;
* credited_at.

---

# 6.8. Analytics Data

## DR-070 — Analytics Event Table

**MUST**

Система має зберігати аналітичні події.

Поля:

* id;
* event_name;
* user_id;
* timestamp;
* source;
* metadata.

---

## 7. Non-Functional Requirements

# 7.1. Performance

## NFR-001 — Bot Response Time

**MUST**

Бот має відповідати користувачу швидко.

Базова ціль:

* звичайна дія: до 2 секунд;
* отримання питання з API: до 3 секунд;
* показ результату: до 2 секунд.

## NFR-002 — API Timeout

**MUST**

Запит до API Quiz Bank має мати timeout.

Якщо timeout спрацював, бот має показати зрозуміле повідомлення.

---

# 7.2. Reliability

## NFR-010 — No Lost Answers

**MUST**

Відповідь користувача не має губитися після натискання кнопки.

## NFR-011 — Safe Retry

**MUST**

Повторний Telegram update не має створювати дубль відповіді або дубль платежу.

## NFR-012 — Payment Idempotency

**MUST**

Платежі мають бути ідемпотентні.

---

# 7.3. Security

## NFR-020 — API Key Protection

**MUST**

Ключі доступу до API не мають бути доступні користувачу.

## NFR-021 — Admin Protection

**MUST**

Адмінські endpoint-и мають бути захищені.

## NFR-022 — Secure Config

**MUST**

Секрети мають зберігатися тільки в змінних середовища або захищеному секрет-сховищі.

---

# 7.4. Privacy

## NFR-030 — Minimal User Data

**MUST**

Система має зберігати тільки ті дані, які потрібні для роботи продукту.

## NFR-031 — No Unnecessary Personal Data

**MUST**

Система не має вимагати email, телефон або адресу користувача для базового використання.

---

# 7.5. Maintainability

## NFR-040 — Modular Code

**MUST**

Код має бути розділений на модулі:

* bot handlers;
* session service;
* progress service;
* mistake service;
* subscription service;
* payment service;
* API client;
* analytics service.

## NFR-041 — Test Coverage

**MUST**

Ключова бізнес-логіка має бути покрита тестами.

Особливо:

* прогрес;
* помилки;
* ліміти;
* платежі;
* підписки;
* API error handling.

---

## 8. Error Handling Requirements

## ER-001 — Unknown Callback

**MUST**

Якщо користувач натиснув застарілу або невідому кнопку, бот має показати безпечне повідомлення і повернути користувача до актуального екрану.

## ER-002 — API Unavailable

**MUST**

Якщо API недоступний, бот має повідомити користувача і не списувати ліміт.

## ER-003 — Payment Failed

**MUST**

Якщо платіж не пройшов, бот має повідомити користувача і не активувати підписку.

## ER-004 — Session Interrupted

**MUST**

Якщо сесія перервана, користувач має мати можливість почати нову сесію.

## ER-005 — Duplicate Answer

**MUST**

Якщо Telegram надіслав дубль update, система не має рахувати відповідь двічі.

---

## 9. Access Rules

## AR-001 — Free Access

Free-користувач має доступ до:

* вибору рівня;
* вибору теми;
* обмеженої кількості питань;
* базового результату;
* короткого прогресу.

## AR-002 — Plus Access

Plus-користувач має доступ до:

* більшого денного ліміту;
* повного прогресу;
* журналу помилок;
* повторення помилок;
* щоденної рекомендації.

## AR-003 — Pro Access

Pro-користувач має доступ до:

* найбільшого денного ліміту;
* розширеної статистики;
* глибшого аналізу помилок;
* персонального плану, якщо функція активна.

---

## 10. Acceptance Criteria for Release 1

Release 1 вважається готовим, якщо виконані умови нижче.

## AC-001 — First User Flow

Користувач може:

1. Запустити бот.
2. Вибрати рівень.
3. Вибрати тему.
4. Почати сесію.
5. Відповісти на питання.
6. Побачити результат.

## AC-002 — Progress Flow

Користувач може:

1. Пройти сесію.
2. Відкрити прогрес.
3. Побачити прогрес по темах.
4. Побачити слабку тему.

## AC-003 — Mistake Flow

Користувач може:

1. Помилитися в питанні.
2. Побачити, що помилка збережена.
3. Натиснути **🔁 Fehler wiederholen**.
4. Пройти сесію з помилок.

## AC-004 — Free Limit Flow

Free-користувач:

1. Проходить доступну кількість питань.
2. Досягає денного ліміту.
3. Бачить зрозуміле повідомлення.
4. Бачить пропозицію Plus.

## AC-005 — Subscription Flow

Користувач може:

1. Відкрити Plus.
2. Почати оплату.
3. Успішно оплатити.
4. Отримати Plus-доступ.
5. Використати Plus-функцію.

## AC-006 — Payment Safety

Один платіж не може бути зарахований двічі.

## AC-007 — API Failure Safety

Якщо API недоступний:

* бот не падає;
* користувач бачить повідомлення;
* ліміт не списується;
* помилка логуються.

## AC-008 — Analytics

Система записує ключові події:

* старт бота;
* вибір рівня;
* старт сесії;
* завершення сесії;
* відкриття прогресу;
* показ paywall;
* оплату.

## AC-009 — German-Only Interface

Усі користувацькі тексти основного Telegram-інтерфейсу показуються німецькою мовою.

---

## 11. Release 1 Done Definition

Release 1 готовий, коли:

1. Основний user flow працює від старту до результату.
2. Питання приходять з API Quiz Bank.
3. Відповіді зберігаються.
4. Прогрес рахується по темах.
5. Помилки зберігаються.
6. Повторення помилок працює.
7. Free-ліміт працює.
8. Plus-підписка працює.
9. Telegram Stars-платіж зараховується без дублювання.
10. API-помилки обробляються без втрати стану.
11. Аналітика основних подій працює.
12. Адмін бачить базові метрики.
13. Ключова логіка покрита тестами.
14. Усі користувацькі тексти Telegram-бота написані німецькою мовою.

---

## 12. Final Requirement Statement

Deutsch Trainer Bot має бути простим Telegram-продуктом, який дає користувачу завершений навчальний цикл:

**вибір рівня → вибір теми → тренування → результат → прогрес → повторення помилок → рекомендація → платне розширення.**

Головна вимога до системи:

> кожна відповідь користувача має покращувати його карту знань.

Оцінка відповіді: **98/100**
