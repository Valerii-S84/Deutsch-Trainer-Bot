# Deutsch Trainer Bot — Analytics Metrics

## 1. Document Purpose

Цей документ описує аналітику **Deutsch Trainer Bot**.

Він фіксує:

* activation;
* retention;
* session completion;
* progress usage;
* mistake repeat usage;
* paywall shown;
* paywall clicked;
* subscription purchased;
* Free → Plus conversion;
* required events;
* required metadata;
* правила attribution;
* інваріанти якості аналітики.

Документ не є BI dashboard design, SQL-запитом, data warehouse schema або інструкцією для конкретного analytics provider.

Його мета — задати строгий, перевірюваний і презентаційно зрозумілий стандарт метрик, який можна перетворити на event tracking plan, dashboards, cohort reports, alerts і product review.

---

## 2. Modeling Standard

Analytics Metrics описані в строгому академічному форматі.

У межах цього документа **Stanford-level standard** означає:

* кожна метрика має визначення;
* кожна метрика має numerator і denominator;
* кожна метрика має required events;
* кожна метрика має measurement window;
* кожна метрика має segmentation fields;
* кожна funnel metric має чіткий порядок подій;
* кожен conversion має attribution rule;
* кожна подія має мінімальну metadata;
* analytics не містить secrets або зайві персональні дані;
* відсутність analytics не ламає навчальний flow користувача.

Головний принцип:

> Аналітика має вимірювати навчальну цінність і бізнес-результат, а не лише кліки.

---

## 3. Analytics Scope

## 3.1. Product Questions

Аналітика має відповідати на питання:

1. Чи користувач доходить до first value?
2. Чи користувач повертається після першої сесії?
3. Чи користувач завершує тренування?
4. Чи користувач відкриває прогрес?
5. Чи користувач повторює помилки?
6. Які paywall-и показуються найчастіше?
7. Які paywall-и отримують click?
8. Чи користувач починає оплату?
9. Чи підписка реально активується?
10. Яка конверсія Free → Plus?

## 3.2. Non-Goals

Цей документ не визначає:

* фінальний analytics provider;
* dashboard layout;
* SQL dialect;
* data warehouse schema;
* attribution model для paid ads;
* A/B testing platform;
* push notification analytics;
* LTV або CAC model.

---

## 4. Core Event Standard

## 4.1. Required Event Fields

Кожна analytics event має містити:

| Field | Required | Meaning |
|---|---:|---|
| `event_name` | Yes | Назва події. |
| `user_id` | No | Internal user ID, якщо користувач відомий. |
| `timestamp` | Yes | Час події. |
| `source` | Yes | Джерело події. |
| `metadata` | No | Мінімальний контекст події. |

## 4.2. Common Metadata

Бажана metadata для більшості user events:

| Field | Purpose |
|---|---|
| `user_plan` | `free`, `plus`, `pro`. |
| `subscription_status` | Поточний access status. |
| `level` | Active CEFR-рівень, якщо релевантно. |
| `theme` | Active theme, якщо релевантно. |
| `session_id` | Training session, якщо релевантно. |
| `session_type` | `regular`, `mistake_review`, `recommended`. |
| `client_entry_point` | Звідки користувач прийшов до дії. |
| `is_first_time_user` | Чи це перший product flow. |

## 4.3. Privacy Rule

Analytics events не мають містити:

* API keys;
* Telegram token;
* payment credentials;
* raw provider payload;
* full Authorization headers;
* raw Quiz Bank responses;
* зайві персональні дані;
* stack traces з secrets.

## 4.4. Append-Only Rule

Analytics events є append-only.

Якщо подія була записана помилково, корекція має бути окремою compensating event або data quality flag.

---

## 5. Required Event Registry

## 5.1. Activation Events

| Event | Trigger |
|---|---|
| `bot_started` | Користувач відкрив бот або натиснув `/start`. |
| `user_created` | Створено нового user record. |
| `level_selected` | Користувач вибрав рівень. |
| `theme_selected` | Користувач вибрав тему. |
| `training_started` | Сесія створена і flow стартував. |
| `training_completed` | Сесія завершена. |
| `result_shown` | Користувач побачив результат. |

## 5.2. Learning Value Events

| Event | Trigger |
|---|---|
| `question_answered` | Accepted User Answer створена. |
| `progress_opened` | Користувач відкрив Progress Screen. |
| `mistakes_opened` | Користувач відкрив Mistake Screen. |
| `mistakes_repeated` | Користувач почав або завершив mistake review. |
| `recommendation_shown` | Рекомендація показана, якщо реалізовано. |
| `daily_limit_hit` | Користувач досяг денного ліміту після реального використання. |

## 5.3. Monetization Events

| Event | Trigger |
|---|---|
| `paywall_shown` | Paywall показаний користувачу. |
| `paywall_clicked` | Користувач натиснув CTA на paywall. |
| `payment_started` | Створено Payment і відкрито payment flow. |
| `payment_succeeded` | Provider підтвердив оплату. |
| `payment_failed` | Оплата не завершилась успішно. |
| `subscription_started` | Paid subscription активована. |
| `subscription_expired` | Paid subscription завершилась. |

## 5.4. Operational Events

| Event | Trigger |
|---|---|
| `quiz_api_request_failed` | Quiz Bank API request failed. |
| `quiz_api_invalid_response` | API response не пройшла validation. |
| `payment_duplicate_event` | Provider event був duplicate. |
| `analytics_event_rejected` | Event відхилено через schema або privacy issue. |

---

## 6. Metric Naming Standard

Метрики називаються у snake_case.

Рекомендовані suffix-и:

| Suffix | Meaning |
|---|---|
| `_rate` | Частка від denominator. |
| `_count` | Абсолютна кількість. |
| `_users` | Унікальні користувачі. |
| `_sessions` | Кількість сесій. |
| `_per_user` | Середнє на користувача. |
| `_conversion` | Conversion між funnel steps. |
| `_ctr` | Click-through rate. |

Приклад:

```text
activation_rate
session_completion_rate
paywall_ctr
free_to_plus_conversion
```

---

## 7. Measurement Windows

## 7.1. Standard Windows

| Window | Meaning |
|---|---|
| same session | Події в межах одного `session_id`. |
| same day | Europe/Berlin calendar date. |
| 24h | 24 години від anchor event. |
| 7d | 7 днів від anchor event. |
| 30d | 30 днів від anchor event. |

## 7.2. Default Timezone

Daily metrics використовують:

```text
Europe/Berlin
```

## 7.3. Unique User Rule

User-level conversion рахується по унікальних `user_id`, а не по кількості кліків.

Event-level diagnostics можуть рахувати raw event count окремо.

---

## 8. Activation

## 8.1. Definition

Activation показує, чи користувач дійшов до першої навчальної цінності.

Activation complete:

```text
level_selected
AND training_completed
AND result_shown
```

## 8.2. Primary Metric

| Metric | Formula |
|---|---|
| `activation_rate` | `activated_users / new_users` |

Where:

| Term | Definition |
|---|---|
| `new_users` | Users with `user_created` in cohort window. |
| `activated_users` | New users who completed activation within 24h of `user_created`. |

## 8.3. Supporting Metrics

| Metric | Formula |
|---|---|
| `start_to_level_selection_rate` | `users_with_level_selected / users_with_bot_started` |
| `level_to_training_start_rate` | `users_with_training_started / users_with_level_selected` |
| `training_start_to_completion_rate` | `users_with_training_completed / users_with_training_started` |
| `completion_to_result_shown_rate` | `users_with_result_shown / users_with_training_completed` |

## 8.4. Required Metadata

Activation events should include:

| Field | Events |
|---|---|
| `is_first_time_user` | `bot_started`, `level_selected`, `training_started`. |
| `level` | `level_selected`, `training_started`, `training_completed`. |
| `theme` | `theme_selected`, `training_started`, `training_completed`. |
| `session_id` | `training_started`, `training_completed`, `result_shown`. |

## 8.5. Interpretation Rule

Activation does not mean paid intent.

Activation means:

```text
the user experienced the learning loop at least once
```

---

## 9. Retention

## 9.1. Definition

Retention показує, чи користувач повертається після першої цінності.

Primary retention anchor:

```text
activation completed at result_shown
```

Якщо activation ще не завершена, fallback anchor:

```text
user_created
```

## 9.2. Primary Metrics

| Metric | Formula |
|---|---|
| `day_1_retention_rate` | `activated_users_active_on_day_1 / activated_users` |
| `day_7_retention_rate` | `activated_users_active_on_day_7 / activated_users` |
| `day_30_retention_rate` | `activated_users_active_on_day_30 / activated_users` |

## 9.3. Active User Definition

User is active if at least one meaningful event occurs:

* `training_started`;
* `question_answered`;
* `training_completed`;
* `progress_opened`;
* `mistakes_opened`;
* `mistakes_repeated`.

Not enough for retention:

* passive payment callback;
* technical API event only;
* duplicate provider event;
* admin-triggered data change.

## 9.4. Paid Retention

| Metric | Formula |
|---|---|
| `paid_day_1_retention_rate` | `paid_users_active_day_1 / users_with_subscription_started` |
| `paid_day_7_retention_rate` | `paid_users_active_day_7 / users_with_subscription_started` |
| `expiration_recovery_rate` | `users_renewed_after_expiration / users_with_subscription_expired` |

## 9.5. Segmentation

Retention should be segmented by:

* first selected level;
* first selected theme;
* user plan;
* activation completed or not;
* first paywall context;
* whether user created a mistake;
* whether user opened progress.

---

## 10. Session Completion

## 10.1. Definition

Session completion показує, чи користувач завершує розпочаті тренування.

## 10.2. Primary Metric

| Metric | Formula |
|---|---|
| `session_completion_rate` | `completed_sessions / started_sessions` |

Where:

| Term | Definition |
|---|---|
| `started_sessions` | Count of `training_started`. |
| `completed_sessions` | Count of `training_completed` with same `session_id`. |

## 10.3. Supporting Metrics

| Metric | Formula |
|---|---|
| `session_abandonment_rate` | `abandoned_sessions / started_sessions` |
| `average_questions_answered_per_session` | `accepted_user_answers / started_sessions` |
| `average_correct_answers_per_session` | `correct_answers / completed_sessions` |
| `mistake_review_completion_rate` | `completed_mistake_review_sessions / started_mistake_review_sessions` |

## 10.4. Required Metadata

`training_started` and `training_completed` should include:

| Field | Purpose |
|---|---|
| `session_id` | Join start/completion. |
| `session_type` | Segment regular vs mistake review. |
| `level` | Level performance. |
| `theme` | Theme performance. |
| `planned_question_count` | Expected session length. |
| `shown_questions_count` | Actual shown questions. |
| `answered_count` | Accepted answers. |
| `correct_answers` | Result quality. |
| `completion_reason` | `completed`, `abandoned`, `api_failed`, if relevant. |

## 10.5. Safety Rule

API failure should not count as user abandonment unless user explicitly leaves after the failure state.

---

## 11. Progress Usage

## 11.1. Definition

Progress usage показує, чи користувач відкриває й використовує карту прогресу.

## 11.2. Primary Metrics

| Metric | Formula |
|---|---|
| `progress_open_rate` | `users_with_progress_opened / activated_users` |
| `progress_opens_per_active_user` | `progress_opened_events / active_users` |
| `post_result_progress_open_rate` | `users_opening_progress_after_result / users_with_result_shown` |

## 11.3. Supporting Metrics

| Metric | Formula |
|---|---|
| `free_progress_usage_rate` | `free_users_with_progress_opened / active_free_users` |
| `paid_progress_usage_rate` | `paid_users_with_progress_opened / active_paid_users` |
| `progress_to_paywall_rate` | `progress_paywall_shown / progress_opened` |
| `progress_paywall_conversion_rate` | `subscription_started_after_progress_paywall / progress_paywall_shown` |

## 11.4. Required Metadata

`progress_opened` should include:

| Field | Purpose |
|---|---|
| `user_plan` | Free vs paid behavior. |
| `progress_view_type` | `short`, `full`, `topic_detail`. |
| `level` | Current level. |
| `topic_status_summary` | Counts of weak/learning/stable/strong if available. |
| `entry_point` | Result screen, home, recommendation, paywall. |

## 11.5. Interpretation Rule

Progress usage is a learning value signal.

Low progress usage can mean:

* progress screen is hard to find;
* first result is not compelling;
* Free progress is too limited;
* users prefer direct practice.

Metric alone must not decide monetization changes without qualitative context.

---

## 12. Mistake Repeat Usage

## 12.1. Definition

Mistake repeat usage показує, чи користувач повертається до власних помилок і тренує їх окремо.

## 12.2. Primary Metrics

| Metric | Formula |
|---|---|
| `mistake_repeat_open_rate` | `users_with_mistakes_opened / users_with_active_mistakes` |
| `mistake_repeat_start_rate` | `users_with_mistakes_repeated / users_with_active_mistakes` |
| `mistake_repeat_usage_per_user` | `mistakes_repeated_events / users_with_active_mistakes` |

## 12.3. Supporting Metrics

| Metric | Formula |
|---|---|
| `mistake_review_completion_rate` | `completed_mistake_review_sessions / started_mistake_review_sessions` |
| `mistake_improvement_rate` | `mistakes_improved / mistakes_repeated` |
| `mistake_resolution_rate` | `mistakes_resolved / active_mistakes_entering_period` |
| `mistake_repeat_paywall_conversion_rate` | `subscription_started_after_mistake_paywall / mistake_paywall_shown` |

## 12.4. Required Metadata

`mistakes_opened` should include:

| Field | Purpose |
|---|---|
| `active_mistake_count` | User eligibility for repeat. |
| `user_plan` | Free vs paid access. |
| `level` | Active level. |
| `entry_point` | Result, progress, home, recommendation. |

`mistakes_repeated` should include:

| Field | Purpose |
|---|---|
| `session_id` | Mistake review session. |
| `active_mistake_count` | Input size. |
| `items_repeated_count` | Actual repeated items. |
| `resolved_count` | Resolved during session. |
| `improved_count` | Improved during session. |
| `user_plan` | Access analysis. |

## 12.5. Eligibility Rule

Mistake repeat metrics should use eligible users as denominator.

Eligible user:

```text
user has at least one active Mistake
```

Using all users as denominator is allowed only for broad product adoption metrics and must be labeled clearly.

---

## 13. Paywall Shown

## 13.1. Definition

`paywall_shown` вимірює exposure до платної пропозиції.

Paywall shown is valid only if:

* user has seen product value first;
* paywall context is allowed;
* paywall copy is German;
* event includes `paywall_context`.

## 13.2. Required Metadata

`paywall_shown` must include:

| Field | Required | Purpose |
|---|---:|---|
| `paywall_context` | Yes | Where paywall appeared. |
| `trigger` | Yes | Specific trigger. |
| `plan_offered` | Yes | `plus` or `pro`. |
| `user_plan` | Yes | Current plan. |
| `subscription_status` | Yes | Current access status. |
| `level` | No | Level context. |
| `theme` | No | Theme context. |
| `daily_limit_state` | No | Limit context. |
| `active_mistake_count` | No | Mistake context. |
| `progress_view_type` | No | Progress context. |

## 13.3. Paywall Context Registry

| Context | Meaning |
|---|---|
| `after_result` | Після результату сесії. |
| `weak_topic` | Після виявлення слабкої теми. |
| `repeated_mistake` | Після повторної помилки. |
| `daily_limit_hit` | Після досягнення денного ліміту. |
| `full_progress_access` | Перед повною картою прогресу. |
| `mistake_repeat_access` | Перед повним повторенням помилок. |
| `subscription_expired` | Після завершення paid access. |

## 13.4. Primary Metrics

| Metric | Formula |
|---|---|
| `paywall_shown_users` | Unique users with `paywall_shown`. |
| `paywall_shown_count` | Count of `paywall_shown` events. |
| `paywall_exposure_rate` | `paywall_shown_users / activated_free_users`. |
| `paywall_frequency_per_user` | `paywall_shown_count / paywall_shown_users`. |

## 13.5. Quality Rule

Paywall exposure should not be maximized blindly.

Repeated paywall frequency without clicks can indicate fatigue.

---

## 14. Paywall Clicked

## 14.1. Definition

`paywall_clicked` вимірює explicit purchase intent after paywall exposure.

## 14.2. Primary Metrics

| Metric | Formula |
|---|---|
| `paywall_ctr` | `paywall_clicked / paywall_shown` |
| `paywall_click_users_rate` | `users_with_paywall_clicked / users_with_paywall_shown` |
| `paywall_to_payment_start_rate` | `users_with_payment_started_after_paywall / users_with_paywall_clicked` |

## 14.3. Required Metadata

`paywall_clicked` must include:

| Field | Required | Purpose |
|---|---:|---|
| `paywall_context` | Yes | Attribution to shown paywall. |
| `plan_offered` | Yes | Offered plan. |
| `cta_id` | Yes | Which CTA was clicked. |
| `user_plan` | Yes | Current plan. |
| `paywall_event_id` | Should | Link to preceding paywall exposure. |

## 14.4. Attribution Rule

Default attribution:

```text
paywall_clicked is attributed to the most recent paywall_shown
for the same user within 24h
```

If `paywall_event_id` exists, it overrides time-based attribution.

---

## 15. Subscription Purchased

## 15.1. Definition

Subscription purchased means paid access was actually activated.

Primary event:

```text
subscription_started
```

`payment_succeeded` alone is not enough, because paid access must be credited.

## 15.2. Primary Metrics

| Metric | Formula |
|---|---|
| `subscription_purchased_users` | Unique users with `subscription_started`. |
| `subscription_purchased_count` | Count of `subscription_started`. |
| `payment_success_rate` | `payment_succeeded / payment_started`. |
| `payment_to_subscription_rate` | `subscription_started / payment_succeeded`. |
| `payment_to_credit_time_p50` | Median time from `payment_succeeded` to `subscription_started`. |

## 15.3. Required Metadata

`subscription_started` must include:

| Field | Required | Purpose |
|---|---:|---|
| `plan` | Yes | `plus` or `pro`. |
| `previous_plan` | Yes | Usually `free` or previous paid plan. |
| `payment_id` | Yes | Internal payment reference. |
| `provider` | Yes | `telegram_stars` for Release 1. |
| `paywall_context` | Should | Purchase attribution. |
| `started_at` | Yes | Subscription start. |
| `expires_at` | Should | Subscription end, if applicable. |

## 15.4. Safety Rule

Duplicate provider event must not create duplicate `subscription_started`.

Metric source for purchased subscriptions is credited subscription state, not raw provider callbacks.

---

## 16. Free → Plus Conversion

## 16.1. Definition

Free → Plus conversion показує, яка частка Free-користувачів стала Plus-користувачами.

Primary conversion event:

```text
subscription_started with plan = plus
```

## 16.2. Primary Metric

| Metric | Formula |
|---|---|
| `free_to_plus_conversion_rate` | `free_users_converted_to_plus / activated_free_users` |

Where:

| Term | Definition |
|---|---|
| `activated_free_users` | Users who completed activation while on Free. |
| `free_users_converted_to_plus` | Activated Free users with `subscription_started(plan=plus)` within attribution window. |

Default attribution window:

```text
30d after activation
```

## 16.3. Funnel Metrics

| Metric | Formula |
|---|---|
| `free_paywall_exposure_rate` | `free_users_with_paywall_shown / activated_free_users` |
| `free_paywall_ctr` | `free_users_with_paywall_clicked / free_users_with_paywall_shown` |
| `free_payment_start_rate` | `free_users_with_payment_started / free_users_with_paywall_clicked` |
| `free_payment_success_rate` | `free_users_with_payment_succeeded / free_users_with_payment_started` |
| `free_to_plus_credit_rate` | `free_users_with_subscription_started_plus / free_users_with_payment_succeeded_plus` |

## 16.4. Context Conversion Metrics

| Metric | Formula |
|---|---|
| `daily_limit_to_plus_conversion_rate` | `plus_subscriptions_after_daily_limit_paywall / daily_limit_paywall_shown` |
| `progress_to_plus_conversion_rate` | `plus_subscriptions_after_progress_paywall / progress_paywall_shown` |
| `mistake_repeat_to_plus_conversion_rate` | `plus_subscriptions_after_mistake_paywall / mistake_paywall_shown` |
| `after_result_to_plus_conversion_rate` | `plus_subscriptions_after_result_paywall / after_result_paywall_shown` |

## 16.5. Attribution Rule

Default rule:

```text
subscription_started(plan=plus)
is attributed to the most recent paywall_clicked
for the same user within 7d
```

If no click exists:

```text
attribute to the most recent paywall_shown within 7d
```

If no paywall exists:

```text
conversion_source = direct_subscription_open
```

## 16.6. Exclusion Rule

Do not include in Free → Plus denominator:

* users who were already Plus before cohort start;
* users whose first paid plan was Pro, unless separately counted;
* test users;
* admin users;
* duplicate user records;
* users without activation, unless metric is explicitly named `all_free_to_plus_conversion_rate`.

---

## 17. Full Funnel Standard

## 17.1. Product Funnel

```text
bot_started
  -> user_created
  -> level_selected
  -> theme_selected
  -> training_started
  -> training_completed
  -> result_shown
  -> progress_opened OR mistakes_opened
  -> paywall_shown
  -> paywall_clicked
  -> payment_started
  -> payment_succeeded
  -> subscription_started
```

## 17.2. Funnel Step Rules

| Step | Required Event | Notes |
|---|---|---|
| Start | `bot_started` | Can include returning users. |
| New user | `user_created` | New-user cohorts. |
| Level selected | `level_selected` | Required for activation. |
| Theme selected | `theme_selected` | May be skipped if recommended default exists. |
| Training started | `training_started` | Session begins. |
| Training completed | `training_completed` | Completion. |
| Result shown | `result_shown` | First value. |
| Value screen | `progress_opened` or `mistakes_opened` | Learning value. |
| Paywall shown | `paywall_shown` | Monetization exposure. |
| Paywall clicked | `paywall_clicked` | Purchase intent. |
| Payment started | `payment_started` | Invoice/payment flow. |
| Payment succeeded | `payment_succeeded` | Provider success. |
| Subscription started | `subscription_started` | Access credited. |

## 17.3. Optional Step Rule

`theme_selected` may be optional only if the product supports a system-selected recommended theme.

If optional, funnel reports must label this path separately.

---

## 18. Dashboard Metrics

## 18.1. Daily Admin Metrics

Admin dashboard should include:

| Metric | Purpose |
|---|---|
| `total_users` | Overall growth. |
| `new_users_today` | Acquisition. |
| `active_users_today` | Daily activity. |
| `training_sessions_today` | Practice volume. |
| `answers_today` | Learning activity. |
| `session_completion_rate_today` | Session quality. |
| `progress_opened_today` | Progress usage. |
| `mistakes_repeated_today` | Mistake loop usage. |
| `paywall_shown_today` | Monetization exposure. |
| `paywall_clicked_today` | Monetization intent. |
| `subscriptions_started_today` | Paid conversion. |
| `active_subscriptions` | Current paid base. |
| `payment_errors_today` | Payment reliability. |
| `api_errors_today` | Content API reliability. |

## 18.2. Weekly Product Review Metrics

Weekly review should include:

* activation rate;
* day 1 retention;
* day 7 retention;
* session completion rate;
* progress open rate;
* mistake repeat start rate;
* paywall CTR by context;
* payment success rate;
* Free → Plus conversion;
* subscription expiration count;
* expiration recovery rate.

---

## 19. Segmentation Standard

Metrics should be segmentable by:

| Segment | Purpose |
|---|---|
| `user_plan` | Free vs Plus vs Pro behavior. |
| `subscription_status` | Active, expired, pending. |
| `level` | A1–C1 learning behavior. |
| `theme` | Topic demand and friction. |
| `session_type` | Regular vs mistake review. |
| `paywall_context` | Conversion by trigger. |
| `entry_point` | UX source. |
| `cohort_date` | Retention and conversion cohorts. |
| `has_active_mistakes` | Mistake repeat eligibility. |

Segmentation must not expose unnecessary personal data.

---

## 20. Data Quality Rules

## 20.1. Event Ordering

Expected ordering:

```text
training_started before training_completed
payment_started before payment_succeeded
payment_succeeded before subscription_started
paywall_shown before paywall_clicked
```

If events arrive out of order, analytics processing may reorder by timestamp but must not invent missing events.

## 20.2. Idempotency

Analytics must handle duplicates from:

* Telegram update retries;
* payment provider duplicate events;
* user double-clicks;
* retrying failed API calls.

User-level metrics should deduplicate by:

```text
user_id + event_name + relevant entity id + time window
```

## 20.3. Entity IDs

Events should include entity IDs when available:

| Entity | Event Examples |
|---|---|
| `session_id` | `training_started`, `training_completed`, `result_shown`. |
| `payment_id` | `payment_started`, `payment_succeeded`, `subscription_started`. |
| `subscription_id` | `subscription_started`, `subscription_expired`. |
| `paywall_event_id` | `paywall_clicked`. |

## 20.4. Missing Analytics Rule

If analytics write fails:

* user flow continues;
* technical error is logged;
* no user-facing error is shown;
* business metrics mark the period as incomplete if loss is material.

---

## 21. Metric Definitions Summary

| Metric | Numerator | Denominator |
|---|---|---|
| `activation_rate` | Activated users | New users |
| `day_1_retention_rate` | Activated users active on day 1 | Activated users |
| `day_7_retention_rate` | Activated users active on day 7 | Activated users |
| `session_completion_rate` | Completed sessions | Started sessions |
| `progress_open_rate` | Users with progress opened | Activated users |
| `mistake_repeat_start_rate` | Users with mistakes repeated | Users with active mistakes |
| `paywall_exposure_rate` | Users with paywall shown | Activated Free users |
| `paywall_ctr` | Paywall clicks | Paywall shown |
| `payment_success_rate` | Payment succeeded | Payment started |
| `subscription_purchase_rate` | Subscription started | Payment succeeded |
| `free_to_plus_conversion_rate` | Activated Free users converted to Plus | Activated Free users |

---

## 22. Acceptance Criteria

Analytics Metrics standard is acceptable for Release 1 if:

1. Activation has a formal definition and formula.
2. Retention has day 1 and day 7 definitions.
3. Session completion has numerator and denominator.
4. Progress usage is measured through `progress_opened`.
5. Mistake repeat usage is measured only against eligible users.
6. `paywall_shown` has required context metadata.
7. `paywall_clicked` is attributable to a shown paywall.
8. Subscription purchased is based on `subscription_started`, not raw payment callback.
9. Free → Plus conversion has denominator, attribution window and exclusions.
10. Payment funnel separates started, succeeded and credited subscription.
11. Analytics events avoid secrets and unnecessary personal data.
12. Missing analytics does not break the learning flow.
13. Dashboard metrics cover learning, monetization and operational health.

---

## 23. Analytics Invariants

1. Analytics is append-only.
2. User-level conversion uses unique users, not raw clicks.
3. Activation requires completed learning value.
4. Retention requires meaningful user activity.
5. Session completion excludes pure API failure from user abandonment.
6. Mistake repeat metrics use eligible users as denominator.
7. Paywall CTR requires both exposure and click.
8. Subscription purchased means access credited.
9. Free → Plus conversion starts from activated Free users.
10. Payment duplicate events do not inflate subscriptions.
11. Analytics never stores secrets.
12. Product decisions must not rely on a single metric without context.

