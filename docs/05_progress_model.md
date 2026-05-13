# Deutsch Trainer Bot — Progress Model

## 1. Document Purpose

Цей документ описує модель навчального прогресу **Deutsch Trainer Bot**.

Це серце продукту.

Документ фіксує:

* як рахується accuracy;
* як рахується coverage;
* як рахується stability;
* як рахується weakness;
* як рахується recency;
* як працює mistake resolution;
* як визначається статус теми;
* як формується денна рекомендація;
* які інваріанти потрібні, щоб карта знань була чесною.

Документ не є SQL-схемою, кодом або UI-специфікацією.

Його мета — дати формальну, перевірювану й презентаційно зрозумілу модель, яку можна перетворити на реалізацію, тести, аналітику й продуктову аргументацію.

---

## 2. Modeling Standard

Модель побудована в строгому академічному форматі:

* кожна метрика має визначення;
* кожна метрика має джерело даних;
* кожна метрика має формулу або deterministic rule;
* кожна метрика має діапазон значень;
* кожна метрика має edge cases;
* усі статуси мають явні thresholds;
* усі правила придатні для unit tests;
* усі рекомендації мають пояснювану причину.

Модель свідомо уникає opaque “AI score”.

Користувач має отримувати просту відповідь, але система має мати доказову логіку.

---

## 3. Core Principle

Головний принцип:

> Кожна відповідь користувача має покращувати карту знань або створювати точний сигнал для повторення.

Це означає:

* правильна відповідь покращує accuracy, coverage або stability;
* неправильна відповідь створює або оновлює weakness і mistake;
* повторення помилки впливає на stability і mistake resolution;
* давня тема підвищує recency risk;
* рекомендація має базуватися на вимірюваному стані, а не на випадковому виборі.

---

## 4. Scope of the Progress Model

## 4.1. Unit of Progress

Базова одиниця прогресу:

```text
User + Level + Theme
```

Ця одиниця зберігається як **Progress Topic**.

Приклад:

```text
User 123 + A2 + Artikel
```

## 4.2. Supported Levels

Модель підтримує рівні:

* A1
* A2
* B1
* B2
* C1

Прогрес не змішується між рівнями.

Одна тема на A2 і така сама тема на B1 — це два різні Progress Topic.

## 4.3. Supported Theme State

Кожна тема має:

* accuracy;
* coverage;
* stability;
* weakness;
* recency;
* topic status;
* recommendation priority.

---

## 5. Input Data

## 5.1. Required Input Objects

Progress Model використовує:

* User;
* Training Session;
* Question Reference;
* User Answer;
* Progress Topic;
* Mistake;
* Recommendation;
* Daily Limit;
* Subscription.

## 5.2. Required Answer Fields

Кожна відповідь має містити:

| Field | Purpose |
|---|---|
| `user_id` | Кому належить відповідь. |
| `session_id` | У якій сесії відповідь дана. |
| `item_id` | Яке питання було видано. |
| `level` | Рівень питання. |
| `theme` | Тема питання. |
| `selected_answer` | Вибір користувача. |
| `correct_answer` | Правильна відповідь на момент перевірки. |
| `is_correct` | Результат відповіді. |
| `response_time_ms` | Час відповіді. |
| `answered_at` | Час відповіді. |
| `session_type` | `regular`, `mistake_review`, `recommended`. |

## 5.3. Required Quiz Bank Fields

Для coverage потрібна інформація з API Quiz Bank:

| Field | Purpose |
|---|---|
| `level` | Рівень питання. |
| `theme` | Тема питання. |
| `available_items_count` | Кількість доступних питань у темі. |
| `item_id` | Стабільний ідентифікатор питання. |
| `metadata` | Додаткова класифікація для прогресу. |

Якщо `available_items_count` тимчасово недоступний, coverage має статус `unknown`, а тема не може отримати статус `strong`.

---

## 6. Score Conventions

## 6.1. Common Scale

Усі основні score зберігаються в діапазоні:

```text
0.00 – 100.00
```

Де:

* `0` означає повну відсутність позитивного сигналу;
* `100` означає максимально сильний позитивний сигнал;
* для `weakness_score` інтерпретація зворотна: `100` означає максимальну слабкість.

## 6.2. Raw Value vs Score

Для кожної метрики бажано розрізняти:

| Type | Meaning |
|---|---|
| raw value | Безпосередній математичний результат. |
| score | Нормалізоване значення 0–100 для продукту. |
| confidence | Довіра до score на основі кількості даних. |

Приклад:

```text
accuracy_raw = 0.80
accuracy_score = 80
accuracy_confidence = medium
```

## 6.3. Confidence Levels

Confidence потрібен, щоб не називати тему сильною після 2 правильних відповідей.

| Confidence | Condition |
|---|---|
| `none` | 0 відповідей. |
| `low` | 1–4 відповіді. |
| `medium` | 5–14 відповідей. |
| `high` | 15+ відповідей. |

Thresholds можуть бути конфігурованими, але Release 1 має мати саме таку базову логіку.

---

## 7. Accuracy Model

## 7.1. Definition

Accuracy показує, яку частку відповідей користувач дав правильно в межах конкретного Progress Topic.

Accuracy відповідає на питання:

> Як часто користувач відповідає правильно в цій темі на цьому рівні?

## 7.2. Formula

```text
accuracy_raw = correct_count / answered_count
accuracy_score = accuracy_raw * 100
```

Якщо `answered_count = 0`:

```text
accuracy_score = 0
accuracy_confidence = none
```

## 7.3. Required Counters

| Counter | Meaning |
|---|---|
| `answered_count` | Усі відповіді по level + theme. |
| `correct_count` | Правильні відповіді по level + theme. |
| `incorrect_count` | Неправильні відповіді по level + theme. |

## 7.4. Example

```text
answered_count = 20
correct_count = 15

accuracy_raw = 15 / 20 = 0.75
accuracy_score = 75
```

## 7.5. Interpretation

| Accuracy Score | Meaning |
|---:|---|
| 0–39 | Дуже слабкий результат. |
| 40–59 | Слабкий результат. |
| 60–74 | Навчання в процесі. |
| 75–89 | Добрий результат. |
| 90–100 | Дуже сильний результат. |

## 7.6. Invariants

* Accuracy не може бути більшою за 100.
* Accuracy не може бути меншою за 0.
* Accuracy без coverage не доводить знання теми.
* Accuracy має рахуватися окремо для кожної пари `level + theme`.

---

## 8. Coverage Model

## 8.1. Definition

Coverage показує, яку частину доступного матеріалу в темі користувач реально бачив.

Coverage відповідає на питання:

> Наскільки повно користувач пройшов тему?

## 8.2. Formula

```text
coverage_raw = unique_items_seen / available_items_count
coverage_score = min(coverage_raw * 100, 100)
```

Якщо `available_items_count = 0` або невідомий:

```text
coverage_score = unknown
coverage_confidence = none
```

## 8.3. Required Counters

| Counter | Meaning |
|---|---|
| `unique_items_seen` | Кількість унікальних item_id, на які користувач відповів. |
| `available_items_count` | Кількість доступних item_id у Quiz Bank для level + theme. |

## 8.4. Example

```text
unique_items_seen = 38
available_items_count = 120

coverage_raw = 38 / 120 = 0.3167
coverage_score = 31.67
```

User-facing German copy:

```text
Artikel: 38 von 120 Fragen
```

## 8.5. Interpretation

| Coverage Score | Meaning |
|---:|---|
| 0–9 | Тема майже не покрита. |
| 10–29 | Низьке покриття. |
| 30–59 | Часткове покриття. |
| 60–79 | Добре покриття. |
| 80–100 | Високе покриття. |

## 8.6. Invariants

* Coverage має використовувати тільки унікальні item_id.
* Повторення того самого питання не збільшує coverage.
* Тема не може бути `strong`, якщо coverage нижче мінімального порогу.
* Якщо Quiz Bank не повертає `available_items_count`, coverage не можна підміняти accuracy.

---

## 9. Stability Model

## 9.1. Definition

Stability показує, чи знання користувача тримається через час.

Stability відповідає на питання:

> Чи пам’ятає користувач тему не тільки зараз, а й після паузи?

## 9.2. Core Idea

Одноразова правильна відповідь не доводить стабільне знання.

Стабільність з’являється, коли користувач:

* відповідає правильно повторно;
* робить це в різні дні;
* не повертається до старої помилки;
* закриває mistake через spaced repetition.

## 9.3. Eligible Items

Item є eligible for stability, якщо:

```text
item_id має відповіді у 2 або більше різні календарні дні
```

Календарний день рахується за timezone:

```text
Europe/Berlin
```

## 9.4. Item Stability Score

Для кожного eligible item визначається `item_stability_score`.

| Condition | Item Stability |
|---|---:|
| Остання відповідь неправильна | 0 |
| Є unresolved mistake | 10 |
| 1 правильне повторення після помилки в той самий день | 30 |
| 1 правильне повторення після помилки в інший день | 55 |
| 2 правильні повторення у різні дні | 75 |
| 3 правильні повторення у різні дні | 90 |
| 3+ правильні повторення з часовим span 7+ днів | 100 |

## 9.5. Topic Stability Formula

```text
stability_score = average(item_stability_score for eligible_items)
```

Якщо eligible items відсутні:

```text
stability_score = 0
stability_confidence = none
```

## 9.6. Stability Confidence

| Confidence | Condition |
|---|---|
| `none` | 0 eligible items. |
| `low` | 1–2 eligible items. |
| `medium` | 3–7 eligible items. |
| `high` | 8+ eligible items. |

## 9.7. Example

```text
eligible item scores = [75, 55, 90, 10]

stability_score = (75 + 55 + 90 + 10) / 4 = 57.5
```

## 9.8. Invariants

* Stability не може бути високою без повторень у різні дні.
* Mistake review session може підвищити stability тільки якщо відповідь правильна.
* Неправильна повторна відповідь знижує stability.
* Resolved mistake підвищує stability, але не гарантує статус `strong` без coverage.

---

## 10. Weakness Model

## 10.1. Definition

Weakness показує, наскільки тема є проблемною для користувача.

Weakness відповідає на питання:

> Де користувач найімовірніше помилиться знову?

## 10.2. Direction of Score

Weakness має зворотну інтерпретацію:

```text
0 = слабкості майже немає
100 = тема дуже слабка
```

## 10.3. Components

Weakness складається з п’яти компонентів:

| Component | Meaning |
|---|---|
| `error_component` | Частка неправильних відповідей. |
| `repeat_mistake_component` | Частка повторних помилок. |
| `unresolved_mistake_component` | Активні незакриті помилки. |
| `instability_component` | Низька stability. |
| `recency_risk_component` | Давно не тренована тема. |

## 10.4. Component Formulas

```text
error_component = 1 - accuracy_raw
```

```text
repeat_mistake_component = repeated_mistake_count / max(mistake_count, 1)
```

```text
unresolved_mistake_component = unresolved_mistake_count / max(unique_items_seen, 1)
```

```text
instability_component = 1 - (stability_score / 100)
```

```text
recency_risk_component = recency_risk_score / 100
```

## 10.5. Weighted Formula

Release 1 базова формула:

```text
weakness_raw =
  0.30 * error_component +
  0.25 * unresolved_mistake_component +
  0.20 * repeat_mistake_component +
  0.15 * instability_component +
  0.10 * recency_risk_component

weakness_score = weakness_raw * 100
```

Weights можуть бути налаштовуваними, але сума має дорівнювати 1.00.

## 10.6. Interpretation

| Weakness Score | Meaning |
|---:|---|
| 0–19 | Низька слабкість. |
| 20–39 | Помірна слабкість. |
| 40–59 | Помітна слабкість. |
| 60–79 | Сильна слабкість. |
| 80–100 | Критична слабкість. |

## 10.7. Invariants

* Weakness має зростати після неправильних відповідей.
* Weakness має зростати після повторних помилок.
* Weakness має спадати після resolved mistakes.
* Weakness не має ставати 0, якщо є unresolved mistakes.
* Weakness має впливати на денну рекомендацію.

---

## 11. Recency Model

## 11.1. Definition

Recency показує, коли користувач востаннє тренував тему.

Recency відповідає на питання:

> Чи не настав час повернутися до цієї теми?

## 11.2. Base Value

```text
days_since_last_practice = today_berlin - date(last_practiced_at_berlin)
```

Якщо тема ніколи не тренувалась:

```text
days_since_last_practice = null
recency_risk_score = 100
```

## 11.3. Recency Risk Score

| Days Since Last Practice | Recency Risk |
|---:|---:|
| 0 | 0 |
| 1 | 10 |
| 2 | 20 |
| 3 | 35 |
| 4–6 | 50 |
| 7–13 | 70 |
| 14+ | 90 |
| never practiced | 100 |

## 11.4. User-Facing Examples

```text
Das Thema „Artikel“ wurde seit 5 Tagen nicht geübt.
```

```text
Du hast „Dativ“ heute schon geübt.
```

## 11.5. Invariants

* Recency uses Europe/Berlin date.
* Recency не має самостійно робити тему weak, якщо інші сигнали сильні.
* Recency має підвищувати priority для повторення.
* Тема з високою weakness і високим recency risk має мати високий recommendation priority.

---

## 12. Mistake Resolution Model

## 12.1. Definition

Mistake Resolution описує, як помилка переходить від `new` до `resolved`.

Мета:

* не закривати помилку занадто рано;
* винагороджувати правильні повторення;
* враховувати spaced repetition;
* не приховувати нестабільне знання.

## 12.2. Mistake Statuses

| Status | Meaning |
|---|---|
| `new` | Помилка створена після першої неправильної відповіді. |
| `repeated` | Користувач знову помилився в цьому item або темі. |
| `improved` | Користувач правильно відповів під час повторення, але доказ ще недостатній. |
| `resolved` | Користувач правильно повторив помилку кілька разів у різні дні. |

## 12.3. State Transitions

```text
new
  ├─ wrong again → repeated
  └─ correct repeat → improved

repeated
  ├─ wrong again → repeated
  └─ correct repeat → improved

improved
  ├─ wrong again → repeated
  ├─ correct repeat same day → improved
  └─ correct repeat on later day with threshold met → resolved

resolved
  └─ wrong again → repeated
```

## 12.4. Resolution Threshold

Release 1 базове правило:

```text
resolved requires:
  successful_repeats_count >= 3
  AND successful_repeat_days_count >= 2
  AND last_wrong_answer is before the successful repeat sequence
```

Stronger optional rule:

```text
resolved requires:
  successful_repeats_count >= 3
  AND successful_repeat_days_count >= 3
```

Release 1 використовує базове правило, але система має бути готова до stronger rule через конфігурацію.

## 12.5. Mistake Counters

| Counter | Meaning |
|---|---|
| `mistake_count` | Кількість неправильних відповідей по item. |
| `successful_repeats_count` | Кількість правильних повторень після помилки. |
| `successful_repeat_days_count` | Кількість різних днів з правильним повторенням. |
| `last_mistake_at` | Остання неправильна відповідь. |
| `last_successful_repeat_at` | Останнє правильне повторення. |

## 12.6. Invariants

* Одна правильна відповідь не закриває Mistake.
* Same-day repeats можуть покращити статус, але не доводять retention.
* Wrong answer after `improved` скидає progress до `repeated`.
* Wrong answer after `resolved` reopens mistake as `repeated`.
* Resolved mistake має знижувати weakness і підвищувати stability.

---

## 13. Topic Status Model

## 13.1. Definition

Topic Status — це короткий product-facing стан теми.

Він агрегує:

* accuracy;
* coverage;
* stability;
* weakness;
* recency;
* confidence.

## 13.2. Statuses

| Status | Meaning |
|---|---|
| `new` | Недостатньо даних для оцінки. |
| `weak` | Тема проблемна й потребує уваги. |
| `learning` | Користувач навчається, але знання ще не стабільне. |
| `stable` | Тема загалом засвоєна, але ще не максимально сильна. |
| `strong` | Тема добре покрита, точна й стабільна. |

## 13.3. Required Thresholds

Release 1 thresholds:

| Status | Conditions |
|---|---|
| `new` | `answered_count < 5` OR `coverage_score < 10`. |
| `weak` | `weakness_score >= 60` OR `accuracy_score < 60` OR `unresolved_mistake_count >= 3`. |
| `learning` | `accuracy_score >= 60` AND `coverage_score >= 10` AND not weak AND not stable. |
| `stable` | `accuracy_score >= 75` AND `coverage_score >= 40` AND `stability_score >= 60` AND `weakness_score < 40`. |
| `strong` | `accuracy_score >= 85` AND `coverage_score >= 70` AND `stability_score >= 75` AND `weakness_score < 25` AND `accuracy_confidence = high` AND `stability_confidence = high`. |

## 13.4. Priority Order

Status визначається в такому порядку:

1. `new`
2. `weak`
3. `strong`
4. `stable`
5. `learning`

Це важливо: weak overrides high accuracy, якщо є repeated mistakes.

## 13.5. Examples

### Example A — High Accuracy, Low Coverage

```text
accuracy_score = 100
coverage_score = 4
stability_score = 0
weakness_score = 10

topic_status = new
```

Explanation:

```text
2 правильні відповіді не доводять знання всієї теми.
```

### Example B — Many Errors

```text
accuracy_score = 52
coverage_score = 35
stability_score = 20
weakness_score = 72

topic_status = weak
```

### Example C — Strong Topic

```text
accuracy_score = 89
coverage_score = 76
stability_score = 82
weakness_score = 12

topic_status = strong
```

## 13.6. Invariants

* Topic Status має бути deterministic.
* Topic Status не має залежати від UI.
* Topic Status має бути reproducible з Progress Topic + Mistake data.
* Topic Status має оновлюватися після кожної User Answer.

---

## 14. Daily Recommendation Model

## 14.1. Definition

Daily Recommendation — це коротка персональна порада, що тренувати зараз.

Вона відповідає на питання:

```text
Was soll ich heute üben?
```

## 14.2. Recommendation Inputs

Daily Recommendation використовує:

| Input | Purpose |
|---|---|
| active level | Не рекомендувати інший рівень без явної причини. |
| selected theme | Враховувати поточний намір користувача. |
| topic_status | Визначити weak/learning/stable topics. |
| weakness_score | Знайти найбільш проблемні теми. |
| recency_risk_score | Повернути давно не треновані теми. |
| unresolved mistakes | Пріоритет повторення помилок. |
| stability_score | Виявити нестабільне знання. |
| daily limit | Не радити дію, яку користувач не може виконати. |
| subscription plan | Врахувати доступ до повторення помилок і повного прогресу. |
| API availability | Не радити тему без питань. |

## 14.3. Recommendation Candidate Types

| Type | Meaning |
|---|---|
| `repeat_mistakes` | Повторити активні помилки. |
| `practice_weak_topic` | Тренувати слабку тему. |
| `restore_recency` | Повернутися до давно не тренованої теми. |
| `increase_coverage` | Пройти більше питань у темі з низьким coverage. |
| `continue_learning` | Продовжити активну тему. |
| `upgrade_plan` | Показати Plus/Pro, якщо користувач уперся в ліміт або платну функцію після value moment. |

## 14.4. Recommendation Priority Formula

Для кожної теми:

```text
topic_priority =
  0.35 * weakness_score +
  0.25 * recency_risk_score +
  0.20 * (100 - stability_score) +
  0.10 * (100 - coverage_score) +
  0.10 * unresolved_mistake_pressure
```

де:

```text
unresolved_mistake_pressure =
  min(unresolved_mistake_count * 20, 100)
```

## 14.5. Candidate Selection Rule

Система вибирає рекомендацію в такому порядку:

1. Якщо денний ліміт вичерпаний → `upgrade_plan`.
2. Якщо є 3+ unresolved mistakes у темі → `repeat_mistakes`.
3. Якщо є тема з `weakness_score >= 60` → `practice_weak_topic`.
4. Якщо є тема з `recency_risk_score >= 70` і `stability_score < 75` → `restore_recency`.
5. Якщо active theme має низький coverage → `increase_coverage`.
6. Інакше → `continue_learning`.

## 14.6. User-Facing German Copy

Recommendation copy має бути німецькою.

Examples:

```text
Heute solltest du Dativ und Artikel wiederholen.
```

```text
Übe Dativ und wiederhole deine Fehler bei Artikel.
```

```text
Ich brauche noch ein paar Antworten, um eine gute Empfehlung zu geben.
Starte eine kurze Übung.
```

## 14.7. Explanation Fields

Внутрішньо Recommendation має зберігати:

| Field | Meaning |
|---|---|
| `recommendation_type` | Тип рекомендації. |
| `target_level` | Рівень. |
| `target_theme` | Тема, якщо є. |
| `reason_code` | Машинна причина. |
| `reason_summary` | Коротке пояснення для адміна або debug. |
| `copy_de` | User-facing німецький текст. |
| `priority_score` | Чому саме ця рекомендація перша. |

## 14.8. Invariants

* Recommendation не має радити тему без доступних питань.
* Recommendation не має радити платну функцію без коректного paywall context.
* Recommendation copy має бути німецькою.
* Recommendation має бути короткою.
* Recommendation має бути explainable через reason_code.

---

## 15. Overall Progress Score

## 15.1. Purpose

Overall Progress Score потрібен для короткого summary по рівню.

Він не замінює Progress Topic.

## 15.2. Topic Composite Score

Для теми:

```text
topic_composite_score =
  0.35 * accuracy_score +
  0.30 * coverage_score +
  0.25 * stability_score +
  0.10 * (100 - weakness_score)
```

## 15.3. Level Progress Score

Для рівня:

```text
level_progress_score =
  average(topic_composite_score for all available topics in level)
```

Якщо тема ще не має відповідей:

```text
topic_composite_score = 0
```

Це гарантує, що користувач не отримує завищений level progress після проходження лише однієї теми.

## 15.4. Invariants

* Level Progress не має рахуватися тільки по темах, які користувач відкрив.
* Теми без відповідей мають впливати на загальний прогрес рівня.
* Overall score не має приховувати weak topics.

---

## 16. Update Algorithm

## 16.1. On Correct Answer

Після правильної відповіді:

1. Створити User Answer.
2. Збільшити `answered_count`.
3. Збільшити `correct_count`.
4. Додати `item_id` до unique items, якщо його ще не було.
5. Оновити accuracy.
6. Оновити coverage.
7. Оновити stability для item.
8. Якщо item має active Mistake, оновити mistake repeat state.
9. Перерахувати weakness.
10. Перерахувати topic status.
11. Записати analytics event.

## 16.2. On Incorrect Answer

Після неправильної відповіді:

1. Створити User Answer.
2. Збільшити `answered_count`.
3. Додати `item_id` до unique items, якщо його ще не було.
4. Оновити accuracy.
5. Оновити coverage.
6. Створити або оновити Mistake.
7. Знизити item stability.
8. Перерахувати weakness.
9. Перерахувати topic status.
10. Записати analytics event.

## 16.3. On Mistake Review Correct Answer

Після правильної відповіді в mistake review:

1. Створити User Answer.
2. Оновити Mistake successful repeats.
3. Перевірити resolution threshold.
4. Оновити stability.
5. Оновити weakness.
6. Перерахувати topic status.
7. Записати `mistakes_repeated`.

## 16.4. On Daily Recommendation Generation

Під час генерації рекомендації:

1. Завантажити Progress Topic для active level.
2. Завантажити active Mistakes.
3. Перевірити Daily Limit.
4. Перевірити Subscription.
5. Перевірити availability питань у Quiz Bank.
6. Обчислити candidate priorities.
7. Вибрати найкращий candidate.
8. Зберегти Recommendation.
9. Показати German user-facing copy.

---

## 17. Edge Cases

## 17.1. No Answers Yet

Якщо користувач ще не відповідав:

```text
accuracy_score = 0
coverage_score = 0
stability_score = 0
weakness_score = 0
topic_status = new
```

Recommendation:

```text
Ich brauche noch ein paar Antworten, um eine gute Empfehlung zu geben.
Starte eine kurze Übung.
```

## 17.2. High Accuracy, Very Low Coverage

Якщо користувач відповів правильно на 2 з 2 питань:

```text
accuracy_score = 100
coverage_score = low
topic_status = new
```

Тема має лишатися `new`, якщо `answered_count < 5` або `coverage_score < 10`.

## 17.3. High Coverage, Low Accuracy

Якщо користувач бачив багато питань, але часто помиляється:

```text
coverage_score = high
accuracy_score = low
weakness_score = high
topic_status = weak
```

## 17.4. Resolved Mistakes, Old Topic

Якщо помилки закриті, але тема давно не тренувалась:

```text
weakness_score = low
recency_risk_score = high
recommendation_type = restore_recency
```

## 17.5. API Available Items Unknown

Якщо Quiz Bank не повертає `available_items_count`:

```text
coverage_score = unknown
topic_status cannot be strong
```

System має логувати це як content metadata issue.

---

## 18. Test Matrix

## 18.1. Accuracy Tests

| Case | Expected |
|---|---|
| 0 answers | accuracy 0, confidence none. |
| 8 correct / 10 total | accuracy 80. |
| duplicate answer | no change. |
| wrong answer | accuracy decreases. |

## 18.2. Coverage Tests

| Case | Expected |
|---|---|
| 1 unique item answered 3 times | coverage counts 1 item. |
| 38 unique / 120 available | coverage 31.67. |
| available count unknown | coverage unknown, not strong. |

## 18.3. Stability Tests

| Case | Expected |
|---|---|
| correct once today | stability low/none. |
| correct on two different days | stability increases. |
| wrong after improvement | stability decreases. |
| 3 correct repeats over 7+ days | high stability. |

## 18.4. Weakness Tests

| Case | Expected |
|---|---|
| repeated mistakes | weakness increases. |
| unresolved mistakes | weakness remains above low. |
| resolved mistakes | weakness decreases. |
| old weak topic | high priority. |

## 18.5. Mistake Resolution Tests

| Case | Expected |
|---|---|
| 1 correct repeat | improved, not resolved. |
| 3 correct repeats across 2 days | resolved. |
| wrong after resolved | repeated. |
| wrong after improved | repeated. |

## 18.6. Recommendation Tests

| Case | Expected |
|---|---|
| daily limit hit | upgrade_plan. |
| 3+ unresolved mistakes | repeat_mistakes. |
| weakness >= 60 | practice_weak_topic. |
| old unstable topic | restore_recency. |
| insufficient data | ask for short exercise. |

---

## 19. Product Interpretation

## 19.1. What User Sees

Користувач не має бачити складні формули.

Користувач має бачити коротку німецьку відповідь:

```text
Starke Themen:
✅ Wortschatz Alltag — 84%

Schwache Themen:
⚠️ Dativ — 47%

Empfehlung für heute:
Übe Dativ und wiederhole deine Fehler bei Artikel.
```

## 19.2. What System Knows

Система має знати:

* чому Dativ слабкий;
* чи проблема в accuracy;
* чи проблема в stability;
* чи проблема в unresolved mistakes;
* чи тема давно не тренувалась;
* чи користувач має доступ до повторення помилок.

## 19.3. What Admin Can Analyze

Адмін може аналізувати:

* теми з найнижчим accuracy;
* теми з найнижчим coverage;
* теми з найнижчим stability;
* теми з найбільшим weakness;
* частоту повторення помилок;
* conversion після paywall на progress або mistake repeat.

---

## 20. Model Integrity Checklist

Перед реалізацією або зміною Progress Model потрібно перевірити:

* accuracy рахується як correct / total;
* coverage рахується по unique item_id;
* stability вимагає повторень у різні дні;
* weakness зростає від помилок і повторних помилок;
* recency використовує Europe/Berlin;
* одна правильна відповідь не закриває mistake;
* topic status не стає strong без coverage і stability;
* daily recommendation має reason_code;
* daily recommendation не радить недоступну дію;
* user-facing recommendation copy німецькою;
* метрики не змішуються між A1, A2, B1, B2, C1.

---

## 21. Final Progress Statement

Progress Model Deutsch Trainer Bot не є простим відсотком правильних відповідей.

Прогрес складається з:

```text
accuracy + coverage + stability - weakness + recency context
```

Помилки не є просто негативним результатом.

Помилки є джерелом персонального тренування:

```text
Mistake → Repeat → Improved → Resolved → Higher Stability
```

Денна рекомендація є видимим продуктом цієї моделі:

```text
Progress Topic + Mistake + Recency + Daily Limit + Subscription → Recommendation
```

Головний стандарт:

> Користувач має за 10 секунд зрозуміти, що він знає, де помиляється і що тренувати сьогодні.
