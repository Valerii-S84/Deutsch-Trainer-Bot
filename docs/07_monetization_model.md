# Deutsch Trainer Bot — Monetization Model

## 1. Document Purpose

Цей документ описує бізнес-модель **Deutsch Trainer Bot**.

Він фіксує:

* які плани існують;
* що входить у Free, Plus і Pro;
* як працюють денні ліміти;
* які функції є платними;
* як використовується Telegram Stars;
* коли показується paywall;
* як виглядає conversion funnel;
* що відбувається після завершення підписки;
* які бізнес-інваріанти не можна порушувати.

Документ не задає фінальні ціни.

Ціни, тривалість підписки й точні числові денні ліміти мають бути визначені окремо як launch configuration.

---

## 2. Modeling Standard

Монетизаційна модель описана в строгому академічному форматі:

* кожен план має визначену роль;
* кожна платна функція має навчальне обґрунтування;
* кожен paywall moment має тригер і заборонені умови;
* кожне право доступу має бути перевірюваним;
* payment lifecycle має бути idempotent;
* завершення підписки не має руйнувати навчальні дані;
* conversion funnel має бути вимірюваним через analytics events.

Модель будується на принципі:

> Користувач платить не за “більше кнопок”, а за кращий навчальний результат.

---

## 3. Monetization Principles

## 3.1. First Value Before Payment

Бот не має просити оплату до того, як користувач побачив користь.

Мінімальний first value:

1. Користувач вибрав рівень.
2. Користувач пройшов сесію.
3. Користувач побачив результат.
4. Користувач побачив слабку тему або базовий прогрес.

Paywall до цього моменту заборонений, крім явного відкриття користувачем розділу планів, якщо такий entry point існує.

## 3.2. Learning Value Alignment

Платна функція має бути пов’язана з навчальною цінністю:

* більше тренування;
* краща карта прогресу;
* повторення помилок;
* персональні рекомендації;
* розширена статистика;
* підготовка до рівня.

## 3.3. German-Only Paywall

Усі paywall, subscription і payment тексти для користувача мають бути німецькою.

Приклад:

```text
Ich habe deine Schwachstellen gefunden.

Mit Plus kannst du deinen vollständigen Fortschritt sehen und deine Fehler gezielt wiederholen.
```

## 3.4. No Data Loss

Монетизація не має карати користувача втратою навчальних даних.

Після завершення підписки:

* прогрес зберігається;
* помилки зберігаються;
* відповіді зберігаються;
* історія платежів зберігається;
* платні view/actions закриваються;
* користувач повертається до Free access.

---

## 4. Plan Overview

## 4.1. Plans

Release 1 підтримує три плани:

| Plan | Role | Business Purpose |
|---|---|---|
| Free | Базовий доступ | Дати відчути цінність продукту. |
| Plus | Основна підписка | Монетизувати прогрес, помилки й щоденне навчання. |
| Pro | Розширена підписка | Дати більше активним користувачам і higher-value сегменту. |

## 4.2. Plan Hierarchy

```text
Free < Plus < Pro
```

Інваріант:

```text
Pro must include all Plus capabilities.
Plus must include all Free capabilities.
```

## 4.3. Plan Configuration Fields

Кожен план має конфігурацію:

| Field | Meaning |
|---|---|
| `plan_code` | `free`, `plus`, `pro`. |
| `display_name_de` | Назва плану німецькою. |
| `daily_question_limit` | Денний ліміт питань. |
| `progress_detail_level` | Рівень деталізації прогресу. |
| `mistake_repeat_access` | Доступ до повторення помилок. |
| `recommendation_access` | Доступ до рекомендацій. |
| `advanced_stats_access` | Доступ до розширеної статистики. |
| `payment_required` | Чи потрібна оплата. |
| `available_for_purchase` | Чи продається план зараз. |

## 4.4. Numeric Limit Policy

Точні числові значення `daily_question_limit` не фіксуються в цьому документі.

Вони мають бути задані перед запуском у конфігурації продукту.

Обов’язкове співвідношення:

```text
free_daily_question_limit < plus_daily_question_limit < pro_daily_question_limit
```

---

## 5. Free Plan

## 5.1. Purpose

Free має довести користувачу цінність продукту до оплати.

Free не має бути порожнім demo.

## 5.2. Included Capabilities

Free включає:

* запуск бота;
* вибір рівня A1–C1;
* вибір теми;
* обмежену кількість питань на день;
* короткі тренувальні сесії;
* базовий результат після сесії;
* короткий прогрес;
* базову рекомендацію;
* збереження відповідей;
* збереження помилок.

## 5.3. Restricted Capabilities

Free може обмежувати:

* повну карту прогресу;
* повний журнал помилок;
* необмежене або розширене повторення помилок;
* детальну статистику;
* великий денний ліміт;
* персональний навчальний план.

## 5.4. Free Success Criterion

Free успішний, якщо користувач:

* проходить першу сесію;
* бачить слабку тему;
* розуміє, що бот зберігає прогрес;
* бачить логічну причину перейти в Plus.

---

## 6. Plus Plan

## 6.1. Purpose

Plus — основний платний план.

Він монетизує головну цінність продукту:

```text
progress + mistakes + recommendations + more daily practice
```

## 6.2. Included Capabilities

Plus включає:

* більший денний ліміт питань;
* повну карту прогресу;
* прогрес по темах;
* сильні й слабкі теми;
* журнал помилок;
* повторення помилок;
* щоденну рекомендацію;
* доступ до більшої кількості тренувань;
* paywall-free доступ до Plus-функцій.

## 6.3. Plus Value Proposition

User-facing German copy:

```text
Plus

Mehr Übungen pro Tag.
Vollständiger Fortschritt.
Fehler gezielt wiederholen.
Tägliche Empfehlungen.
```

## 6.4. Plus Success Criterion

Plus успішний, якщо платний користувач:

* тренується частіше;
* відкриває повний прогрес;
* повторює помилки;
* повертається після першого дня;
* бачить зниження повторних помилок.

---

## 7. Pro Plan

## 7.1. Purpose

Pro — розширений план для активних користувачів.

Він має бути корисним для користувачів, які:

* тренуються часто;
* хочуть більше статистики;
* готуються до рівня або іспиту;
* хочуть глибший аналіз помилок;
* потребують персональнішого навчального плану.

## 7.2. Included Capabilities

Pro включає все з Plus, а також:

* найбільший денний ліміт;
* розширену статистику;
* глибший аналіз помилок;
* персональний навчальний план, якщо функція активна;
* пріоритетний доступ до нових тем або тренувань, якщо доступно;
* розширений progress history, якщо доступно.

## 7.3. Pro Value Proposition

User-facing German copy:

```text
Pro

Mehr Übungen pro Tag.
Erweiterte Statistik.
Tieferer Fehlerüberblick.
Persönlicher Lernplan.
```

## 7.4. Pro Boundary

Pro не має ламати простоту продукту.

Pro може додавати глибину, але не має змушувати базового користувача бачити складний інтерфейс.

---

## 8. Entitlement Model

## 8.1. Definition

Entitlement — це право користувача на конкретну функцію.

План не має перевірятися “на око” в UI.

Кожна платна дія має перевіряти entitlement.

## 8.2. Core Entitlements

| Entitlement | Free | Plus | Pro |
|---|---:|---:|---:|
| `select_level` | Yes | Yes | Yes |
| `select_theme` | Yes | Yes | Yes |
| `daily_question_limit` | Low | Medium | High |
| `basic_result` | Yes | Yes | Yes |
| `short_progress` | Yes | Yes | Yes |
| `full_progress_map` | Limited / No | Yes | Yes |
| `topic_progress_detail` | Limited | Yes | Yes |
| `mistake_journal` | Limited | Yes | Yes |
| `mistake_repeat` | Limited / No | Yes | Yes |
| `daily_recommendation` | Basic | Yes | Yes |
| `advanced_statistics` | No | Limited / No | Yes |
| `personal_learning_plan` | No | No / Limited | Yes |

## 8.3. Access Check Rule

Перед відкриттям платної функції система перевіряє:

1. User exists.
2. Subscription status.
3. Current plan.
4. Entitlement.
5. Daily Limit.
6. Feature availability.

Якщо entitlement відсутній, система відкриває Paywall Screen, якщо paywall moment дозволений.

## 8.4. Entitlement Invariants

* Pro включає Plus.
* Plus включає Free.
* Завершення підписки не видаляє дані.
* UI не має показувати платну функцію як доступну без entitlement.
* Backend/service layer має перевіряти entitlement незалежно від UI.

---

## 9. Daily Limits

## 9.1. Purpose

Daily Limit контролює кількість питань, які користувач може отримати за день.

Він потрібен для:

* захисту Free economics;
* стимулу до Plus;
* контрольованого використання API Quiz Bank;
* прогнозованої монетизації.

## 9.2. Timezone

Базова timezone:

```text
Europe/Berlin
```

Daily Limit reset відбувається один раз на день за Europe/Berlin date.

## 9.3. Limit Counting Rule

Ліміт списується тільки коли питання реально видано користувачу.

Ліміт не списується, якщо:

* API Quiz Bank недоступний;
* API повернув error;
* питання не було показане;
* Telegram update duplicate;
* користувач натиснув застарілу кнопку;
* payment flow був перерваний.

## 9.4. Limit Hierarchy

```text
Free limit < Plus limit < Pro limit
```

Точні числа мають бути задані в launch configuration:

| Config Key | Meaning |
|---|---|
| `free_daily_question_limit` | Денний ліміт Free. |
| `plus_daily_question_limit` | Денний ліміт Plus. |
| `pro_daily_question_limit` | Денний ліміт Pro. |

## 9.5. Daily Limit Hit Copy

```text
Dein Tageslimit ist erreicht.

Mit Plus kannst du heute weiter üben und deinen vollständigen Fortschritt sehen.
```

Buttons:

```text
⭐ Plus ansehen
📊 Mein Fortschritt
🏠 Hauptmenü
```

## 9.6. Daily Limit Events

Required events:

* `daily_limit_hit`;
* `paywall_shown`;
* `paywall_clicked`, якщо користувач натиснув CTA;
* `training_blocked_by_limit`, якщо такий event додається.

---

## 10. Paid Features

## 10.1. Paid Feature Definition

Paid Feature — це функція, яка збільшує навчальну цінність і вимагає Plus або Pro.

## 10.2. Plus Paid Features

Plus paid features:

* full progress map;
* topic-level progress;
* mistake journal;
* mistake repeat;
* higher daily limit;
* daily recommendation;
* weak topic overview.

## 10.3. Pro Paid Features

Pro paid features:

* highest daily limit;
* advanced statistics;
* deeper mistake analysis;
* personal learning plan;
* exam/level preparation support, якщо активовано;
* priority access to new themes, якщо активовано.

## 10.4. Paid Feature Invariant

Платна функція має відповідати хоча б одному критерію:

* допомагає вчитися частіше;
* допомагає краще бачити прогрес;
* допомагає повторювати помилки;
* допомагає прийняти наступну навчальну дію;
* допомагає підготуватися до рівня.

---

## 11. Telegram Stars Payment Model

## 11.1. Payment Channel

Release 1 використовує:

```text
Telegram Stars
```

для оплати Plus і Pro.

## 11.2. Payment Lifecycle

```text
created → pending → paid → credited
        ↘ failed
        ↘ cancelled
```

## 11.3. Payment Creation Rule

Перед відкриттям Telegram Stars invoice система створює Payment record.

Payment record має містити:

* user_id;
* plan;
* amount;
* currency / Stars unit;
* provider;
* provider_payment_id, якщо вже доступний;
* status;
* idempotency_key;
* created_at.

## 11.4. Payment Verification Rule

Підписка активується тільки після підтвердженого успішного платежу.

Система має перевірити:

1. provider event;
2. payment reference;
3. user ownership;
4. expected plan;
5. idempotency key;
6. current payment status.

## 11.5. Idempotent Credit Rule

Один платіж не може активувати доступ більше одного разу.

Formal invariant:

```text
one provider_payment_id → at most one credited subscription period
```

## 11.6. Payment Success Copy

```text
Plus ist aktiv ✅

Du kannst jetzt mehr üben, deinen vollständigen Fortschritt sehen und deine Fehler gezielt wiederholen.
```

## 11.7. Payment Failure Copy

```text
Die Zahlung wurde nicht abgeschlossen.

Du kannst es noch einmal versuchen.
```

## 11.8. Payment Events

Required events:

* `payment_started`;
* `payment_succeeded`;
* `payment_failed`;
* `subscription_started`;
* `subscription_expired`.

## 11.9. Payment Safety Rules

* Payment failure не відкриває доступ.
* Duplicate provider event не зараховує доступ двічі.
* Payment не має містити зайві персональні дані.
* Payment audit log має бути достатнім для розбору інциденту.
* Telegram Stars provider data не має показуватись користувачу як debug text.

---

## 12. Paywall Model

## 12.1. Paywall Definition

Paywall — це момент, коли система пояснює користувачу платну цінність і пропонує перейти на Plus або Pro.

Paywall не є просто блокуванням.

Paywall має відповідати на питання:

> Яку навчальну користь я отримаю після оплати?

## 12.2. Allowed Paywall Moments

Paywall може з’являтися:

| Moment | Trigger | Primary Plan |
|---|---|---|
| After result | Користувач завершив сесію й побачив слабку тему. | Plus |
| After repeated mistake | Користувач має повторні помилки. | Plus |
| Daily limit hit | Користувач досяг денного ліміту. | Plus |
| Full progress access | Користувач хоче повну карту прогресу. | Plus |
| Mistake repeat access | Користувач хоче повторити збережені помилки. | Plus |
| Advanced stats access | Користувач хоче розширену статистику. | Pro |
| Personal plan access | Користувач хоче персональний план. | Pro |

## 12.3. Forbidden Paywall Moments

Paywall не має з’являтися:

* до першого value moment;
* до першої сесії як примусовий перший екран;
* замість error handling;
* після API failure;
* після payment failure як агресивний повторний продаж;
* якщо користувач уже має entitlement.

## 12.4. Paywall Copy Patterns

### Progress Paywall

```text
Ich habe deine Schwachstellen gefunden.

Mit Plus kannst du deinen vollständigen Fortschritt sehen und deine Fehler gezielt wiederholen.
```

### Daily Limit Paywall

```text
Dein Tageslimit ist erreicht.

Mit Plus kannst du heute weiter üben und deinen vollständigen Fortschritt sehen.
```

### Mistake Paywall

```text
Du hast mehrere offene Fehler.

Mit Plus kannst du sie gezielt wiederholen und schneller schließen.
```

### Pro Paywall

```text
Mit Pro bekommst du erweiterte Statistik, mehr Training und einen tieferen Fehlerüberblick.
```

## 12.5. Paywall Buttons

```text
⭐ Plus aktivieren
🚀 Pro ansehen
🏠 Hauptmenü
```

Optional:

```text
📊 Mein Fortschritt
```

## 12.6. Paywall Events

Required events:

* `paywall_shown`;
* `paywall_clicked`;
* `payment_started`;
* `payment_succeeded`;
* `payment_failed`;
* `subscription_started`.

Paywall event metadata should include:

* `paywall_context`;
* `trigger`;
* `plan_offered`;
* `user_plan`;
* `level`;
* `theme`, if relevant;
* `daily_limit_state`, if relevant.

## 12.7. Paywall Quality Criteria

Good paywall:

* appears after value;
* names the user’s learning need;
* explains the paid benefit;
* has one clear CTA;
* uses German copy;
* does not shame the user.

Bad paywall:

```text
Kaufe Plus.
```

as the only explanation.

---

## 13. Conversion Funnel

## 13.1. Funnel Overview

```text
bot_started
  → level_selected
  → theme_selected
  → training_started
  → training_completed
  → result_shown
  → progress_opened
  → paywall_shown
  → paywall_clicked
  → payment_started
  → payment_succeeded
  → subscription_started
```

## 13.2. Activation Funnel

Activation is complete when:

```text
level_selected + first training_completed + result_shown
```

Activation metrics:

* start to level selection rate;
* level selection to training start rate;
* training start to completion rate;
* result shown rate.

## 13.3. Value Funnel

Value is demonstrated when user sees at least one of:

* weak topic;
* saved mistake;
* progress summary;
* daily recommendation;
* daily limit hit after actual use.

Value events:

* `result_shown`;
* `progress_opened`;
* `mistakes_opened`;
* `daily_limit_hit`;
* `recommendation_shown`, якщо реалізовано.

## 13.4. Paywall Funnel

Paywall funnel:

```text
paywall_shown → paywall_clicked → payment_started
```

Metrics:

* paywall CTR;
* paywall context conversion;
* paywall to payment start rate;
* repeated paywall fatigue.

## 13.5. Payment Funnel

Payment funnel:

```text
payment_started → payment_succeeded → subscription_started
```

Metrics:

* payment success rate;
* payment failure rate;
* duplicate payment event rate;
* payment to credited subscription time.

## 13.6. Upgrade Funnel

Upgrade funnel:

```text
Free → Plus → Pro
```

Metrics:

* Free to Plus conversion;
* Plus to Pro conversion;
* daily limit conversion;
* progress paywall conversion;
* mistake repeat paywall conversion;
* advanced stats paywall conversion.

## 13.7. Retention Funnel

Retention signals:

* day 1 return;
* day 7 return;
* sessions per paid user;
* mistakes repeated per paid user;
* progress opened per paid user;
* subscription renewal;
* subscription expiration without renewal.

---

## 14. Subscription Lifecycle

## 14.1. Lifecycle

```text
none/free → pending → active → expired
                    ↘ failed
                    ↘ cancelled
```

## 14.2. Pending

Subscription може бути `pending`, якщо:

* payment started;
* provider confirmation not yet received;
* access has not been credited.

Pending не відкриває paid access.

## 14.3. Active

Subscription active означає:

* payment confirmed;
* access credited;
* current time < expires_at;
* plan entitlements available.

## 14.4. Expired

Subscription expired означає:

* current time >= expires_at;
* paid entitlements closed;
* user returns to Free access;
* learning data remains stored.

## 14.5. Cancelled

Cancelled означає:

* subscription was explicitly cancelled or invalidated;
* future renewal disabled;
* access policy follows product configuration.

Release 1 має мінімально підтримати expired behavior.

---

## 15. Rules After Subscription Expiration

## 15.1. Access Changes

Після завершення Plus або Pro:

| Capability | After Expiration |
|---|---|
| Basic training | Still available under Free limit. |
| Level selection | Still available. |
| Theme selection | Still available. |
| Basic result | Still available. |
| Short progress | Still available. |
| Full progress map | Locked or limited. |
| Mistake journal | Locked or limited. |
| Mistake repeat | Locked or limited. |
| Daily recommendation | Basic only or limited. |
| Advanced statistics | Locked. |
| Personal learning plan | Locked. |

## 15.2. Data Retention

After expiration, keep:

* User;
* Training Sessions;
* User Answers;
* Progress Topics;
* Mistakes;
* Recommendations history;
* Payments;
* Subscription history;
* Analytics Events.

## 15.3. Expiration Copy

```text
Dein Plus-Zugang ist abgelaufen.

Dein Fortschritt bleibt gespeichert. Mit Plus kannst du wieder mehr üben und deine Fehler gezielt wiederholen.
```

Buttons:

```text
⭐ Plus erneuern
▶️ Üben
```

## 15.4. Expiration Invariants

* Expiration does not delete learning data.
* Expiration does not delete mistakes.
* Expiration does not reset progress.
* User can continue Free training.
* Paid access must close automatically after expiration.
* Renewal must not duplicate old payment credit.

---

## 16. Access Decision Table

| User State | Requested Action | Decision |
|---|---|---|
| Free, under limit | Start regular training | Allow. |
| Free, limit hit | Start regular training | Block and show daily limit paywall. |
| Free | Open short progress | Allow. |
| Free | Open full progress | Show progress paywall after value moment. |
| Free | Repeat mistakes | Allow limited access or show mistake paywall based on config. |
| Plus active | Open full progress | Allow. |
| Plus active | Repeat mistakes | Allow. |
| Plus active | Open advanced statistics | Show Pro paywall if feature is Pro-only. |
| Pro active | Open advanced statistics | Allow. |
| Expired paid plan | Use paid feature | Return to Free behavior and show renewal paywall if appropriate. |
| Payment pending | Use paid feature | Block until confirmed. |
| Payment failed | Use paid feature | Block; show payment failure or plan screen. |

---

## 17. Monetization Analytics

## 17.1. Required Events

| Event | Purpose |
|---|---|
| `daily_limit_hit` | Detect limit-driven conversion. |
| `paywall_shown` | Measure paywall exposure. |
| `paywall_clicked` | Measure paywall intent. |
| `payment_started` | Measure purchase start. |
| `payment_succeeded` | Measure successful payments. |
| `payment_failed` | Measure payment problems. |
| `subscription_started` | Measure activated paid access. |
| `subscription_expired` | Measure churn or renewal opportunity. |

## 17.2. Required Metadata

Paywall and payment events should include:

* user_id;
* plan;
* current_plan;
* paywall_context;
* trigger;
* level;
* theme, if relevant;
* daily_limit_state;
* subscription_status;
* timestamp.

## 17.3. Core Metrics

| Metric | Definition |
|---|---|
| Free to Plus conversion | `subscription_started(Plus) / activated_free_users`. |
| Plus to Pro conversion | `subscription_started(Pro) / active_plus_users`. |
| Paywall CTR | `paywall_clicked / paywall_shown`. |
| Payment success rate | `payment_succeeded / payment_started`. |
| Daily limit conversion | `subscription_started after daily_limit_hit / daily_limit_hit`. |
| Progress paywall conversion | `subscription_started after progress paywall / progress paywall shown`. |
| Mistake paywall conversion | `subscription_started after mistake paywall / mistake paywall shown`. |
| Paid retention | `paid users active after day 1/day 7`. |
| Expiration recovery | `renewals after subscription_expired / subscription_expired`. |

---

## 18. Configuration Checklist

Before Release 1 launch, product owner must define:

* `free_daily_question_limit`;
* `plus_daily_question_limit`;
* `pro_daily_question_limit`;
* Plus price in Telegram Stars;
* Pro price in Telegram Stars;
* subscription duration;
* whether Free has limited mistake repeat;
* whether Plus includes all recommendations;
* whether Pro personal plan is enabled;
* whether one-time purchases are enabled;
* paywall cooldown policy;
* renewal reminder policy.

No implementation should hardcode these values outside configuration.

---

## 19. Monetization Integrity Checklist

Before implementing or changing monetization, verify:

* Free delivers first value before paywall;
* Free limit is lower than Plus limit;
* Plus limit is lower than Pro limit;
* Plus unlocks full progress and mistake repeat;
* Pro includes Plus capabilities;
* paywall copy is German;
* paywall appears only after allowed moments;
* payment is created before Telegram Stars invoice;
* subscription activates only after confirmed payment;
* one payment cannot be credited twice;
* expired subscription returns user to Free;
* expiration does not delete learning data;
* analytics events are recorded for funnel measurement.

---

## 20. Final Monetization Statement

Deutsch Trainer Bot monetizes learning clarity, not artificial friction.

The business model is:

```text
Free proves value.
Plus unlocks progress, mistakes, recommendations, and more practice.
Pro expands depth for highly active learners.
```

The conversion model is:

```text
Training → Result → Weakness / Progress → Paywall → Telegram Stars → Subscription
```

The core business invariant:

> Користувач має платити за кращий навчальний результат, а не за розблокування базового розуміння продукту.
