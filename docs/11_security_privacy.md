# Deutsch Trainer Bot — Security and Privacy

## 1. Document Purpose

Цей документ описує стандарт безпеки та приватності **Deutsch Trainer Bot**.

Він фіксує:

* як обробляється Telegram user ID;
* які персональні дані можна зберігати;
* як захищаються платежі;
* як захищається доступ до API;
* як захищаються адмінські endpoint-и;
* що можна і не можна писати в логи;
* які rate limits потрібні;
* які backup rules потрібні для production.

Документ не є юридичною політикою приватності, DPA, DPIA, production runbook або infrastructure-as-code специфікацією.

Його мета — задати строгий, перевірюваний і презентаційно зрозумілий security/privacy standard, який можна перетворити на implementation controls, tests, operational checklist і release gates.

---

## 2. Security Standard

Security and Privacy описані в строгому академічному форматі.

У межах цього документа **Stanford-level standard** означає:

* кожен trust boundary описаний явно;
* кожен sensitive field має правило зберігання;
* кожен external input вважається недовіреним до валідації;
* кожна дія з доступом має authorization rule;
* кожен secret має правило зберігання і logging ban;
* кожен payment event має idempotency rule;
* кожен admin endpoint має authentication, authorization і audit rule;
* кожен log має data minimization rule;
* кожен backup має protection і restore rule;
* кожне правило придатне для review, test або operational audit.

Головний принцип:

> Бот має зберігати тільки ті дані, які потрібні для навчання, прогресу, платежів і операційної діагностики.

---

## 3. Trust Boundaries

## 3.1. External Systems

Deutsch Trainer Bot взаємодіє з:

| System | Trust Level | Main Risk |
|---|---|---|
| Telegram Bot API | External trusted provider | Duplicate updates, spoofed callbacks if not validated, token leakage. |
| Quiz Bank API | External content provider | Invalid payloads, API key leakage, over-sharing user data. |
| Telegram Stars / payment provider | External payment provider | Duplicate events, fake payment state, raw provider data leakage. |
| Admin interface | Internal privileged surface | Unauthorized data access or operational actions. |
| Analytics / logs | Internal diagnostic surface | PII or secret leakage. |
| Backup storage | Sensitive infrastructure | Full data exposure if backup is leaked. |

## 3.2. Input Rule

Every external input is untrusted until validated.

Це стосується:

* Telegram updates;
* callback data;
* Quiz Bank API responses;
* payment provider events;
* admin request parameters;
* analytics payloads;
* restore/import data.

---

## 4. Telegram User ID

## 4.1. Purpose

`telegram_user_id` використовується для:

* розпізнавання returning user;
* прив’язки Telegram interaction до internal user;
* захисту від дублювання user records;
* ownership checks для сесій, відповідей, прогресу, помилок і підписок.

## 4.2. Storage Rule

`telegram_user_id` можна зберігати в `users`.

Required constraints:

| Control | Rule |
|---|---|
| Uniqueness | `telegram_user_id` має бути унікальним. |
| Ownership | Дії користувача мають виконуватись тільки для його internal `user_id`. |
| No exposure | `telegram_user_id` не показується іншим користувачам. |
| No secret assumption | `telegram_user_id` не вважається secret. |

## 4.3. Logging Rule

Логи можуть містити internal `user_id` для діагностики.

`telegram_user_id` у logs дозволений тільки якщо:

* це потрібно для розбору Telegram-specific incident;
* немає достатнього internal correlation id;
* log не є user-facing;
* log retention і access control захищені.

Preferred diagnostic identifier:

```text
internal user_id
```

## 4.4. Forbidden Uses

Заборонено:

* використовувати `telegram_user_id` як authentication secret;
* передавати `telegram_user_id` у Quiz Bank API без потреби;
* включати `telegram_user_id` у public error messages;
* використовувати `telegram_user_id` як payment idempotency key без додаткового scope.

---

## 5. Personal Data

## 5.1. Minimal Data Rule

Система має зберігати тільки ті персональні дані, які потрібні для роботи продукту.

Release 1 може зберігати:

| Field | Source | Purpose |
|---|---|---|
| `telegram_user_id` | Telegram | User identity mapping. |
| `username` | Telegram | Optional support/debug context. |
| `first_name` | Telegram | Optional display context. |
| `language_code` | Telegram | Optional locale context. |

Release 1 не має вимагати:

* email;
* phone number;
* address;
* real name;
* age;
* passport or identity documents;
* payment card data.

## 5.2. Learning Data

Learning data includes:

* selected level;
* selected theme;
* training sessions;
* user answers;
* progress topics;
* progress history;
* mistakes;
* mistake history;
* recommendations.

Learning data is personal product data and must be protected as user-owned state.

## 5.3. Data Minimization by Destination

| Destination | Allowed Data |
|---|---|
| Quiz Bank API | Learning context only, such as level, theme, item IDs. |
| Payment provider | Payment-required fields only. |
| Analytics | Minimal event context, no secrets. |
| Logs | Minimal diagnostic context, no raw sensitive payloads. |
| Admin views | Aggregated data by default; user-level data only for authorized support/debug tasks. |

## 5.4. User-Facing Privacy Rule

User-facing bot messages must not reveal:

* internal user IDs;
* Telegram IDs;
* payment provider IDs;
* API request IDs;
* stack traces;
* raw errors;
* secret names.

---

## 6. Payments

## 6.1. Payment Provider Boundary

Release 1 uses Telegram Stars for Plus and Pro payments.

The bot stores:

* internal `payment_id`;
* `user_id`;
* plan;
* amount;
* currency or Stars unit;
* provider name;
* provider payment reference;
* payment status;
* idempotency key;
* timestamps.

The bot must not store:

* payment card numbers;
* payment credentials;
* raw provider secrets;
* full unredacted provider payloads;
* debug dumps that include sensitive provider data.

## 6.2. Payment Verification Rule

Paid access opens only after verified payment.

System must verify:

1. provider event authenticity;
2. payment reference;
3. user ownership;
4. expected plan;
5. expected amount;
6. idempotency key;
7. current payment status.

## 6.3. Idempotency Rule

Formal invariant:

```text
one provider_payment_id -> at most one credited subscription period
```

Duplicate provider events must result in idempotent success, not duplicate access.

## 6.4. Payment Logging Rule

Payment logs may include:

* internal `payment_id`;
* internal `user_id`;
* plan;
* status;
* provider name;
* redacted provider reference;
* event timestamp;
* failure category.

Payment logs must not include:

* payment credentials;
* raw provider secrets;
* full provider payload;
* authorization headers;
* card data;
* Telegram bot token.

## 6.5. Payment Access Rule

`payment_succeeded` alone does not unlock paid features.

Paid features unlock only after:

```text
Payment status = credited
AND Subscription status = active
AND current_time < expires_at
```

---

## 7. API Access

## 7.1. Quiz Bank API Key

Quiz Bank API key is a secret.

Rules:

* API key is server-side only;
* API key is never sent to Telegram;
* API key is never committed to repository;
* API key is read from environment or protected secret storage;
* API key is not logged;
* API key is not included in analytics;
* API key is not exposed in error messages.

## 7.2. Transport Rule

Production API traffic must use HTTPS.

Every API request should have:

* timeout;
* request id or correlation id;
* structured error handling;
* response schema validation;
* retry policy for safe reads.

## 7.3. User Data to Quiz Bank

Quiz Bank API should receive only learning context:

Allowed:

* level;
* theme;
* count;
* session type;
* seen item IDs;
* mistake item IDs;
* weak theme keys.

Forbidden unless explicitly required:

* Telegram username;
* Telegram first name;
* raw chat history;
* payment data;
* subscription payment identifiers;
* secrets.

## 7.4. API Response Trust Rule

Quiz Bank responses must be validated before use.

Before validation, response data must not be:

* shown to user;
* stored as trusted snapshot;
* used for progress scoring;
* used for mistake resolution;
* used for recommendations.

## 7.5. API Error Rule

API errors must not reveal:

* API host internals;
* secret names;
* Authorization header;
* raw response body;
* stack trace;
* internal exception message.

User-facing API error copy must be German and generic.

---

## 8. Admin Endpoints

## 8.1. Admin Surface

Admin endpoints may expose:

* total users;
* active users;
* training sessions;
* answers;
* payment counts;
* active subscriptions;
* API errors;
* payment errors;
* learning metrics.

Admin endpoints are privileged and must be protected.

## 8.2. Authentication Rule

Every admin endpoint must require authentication.

Allowed mechanisms are implementation-specific, but must provide:

* non-public access;
* secret or identity-based authentication;
* session/token expiry or revocation capability;
* no hardcoded credentials in repository.

## 8.3. Authorization Rule

Authentication is not enough.

Admin access must check authorization:

| Action | Required Control |
|---|---|
| View aggregate metrics | Admin role. |
| View user-level diagnostics | Elevated admin/support role. |
| Retry operational task | Explicit permission. |
| Export data | Explicit permission and audit. |
| Change configuration | Explicit permission and audit. |

## 8.4. Admin Logging Rule

Admin actions should be audit logged.

Audit log should include:

* admin identity or internal admin id;
* action;
* target entity type;
* target entity id, if relevant;
* timestamp;
* result;
* request id.

Audit log must not include:

* admin credentials;
* full secrets;
* raw payment credentials;
* full sensitive payload dumps.

## 8.5. Admin Data Minimization

Admin dashboards should use aggregated metrics by default.

User-level data should be shown only when necessary for:

* support;
* incident debugging;
* payment reconciliation;
* abuse investigation.

---

## 9. Logs

## 9.1. Log Purpose

Logs exist for:

* debugging;
* incident response;
* payment audit;
* API reliability diagnostics;
* operational monitoring.

Logs do not exist for storing user history or raw payload archives.

## 9.2. Allowed Log Fields

Logs may include:

| Field | Purpose |
|---|---|
| `request_id` | Correlation. |
| `user_id` | Internal diagnostic ownership. |
| `session_id` | Training diagnostics. |
| `payment_id` | Payment diagnostics. |
| `endpoint` | Logical endpoint. |
| `status_code` | HTTP status. |
| `error_category` | Failure class. |
| `duration_ms` | Performance diagnostics. |
| `occurred_at` | Incident time. |

## 9.3. Forbidden Log Data

Logs must not contain:

* API keys;
* Telegram bot token;
* raw Authorization headers;
* payment credentials;
* raw provider secrets;
* full webhook payloads with sensitive data;
* full Quiz Bank raw responses;
* database connection strings;
* `.env` content;
* private keys;
* passwords.

## 9.4. Redaction Rule

If a sensitive value is needed for correlation, log only a redacted form.

Example:

```text
provider_payment_id_redacted = last_6_chars
```

Do not log full tokens even in development-like environments if logs can be shared or persisted.

## 9.5. User-Facing Error Rule

Internal logs and user-facing error messages are separate.

User-facing messages must not expose:

* stack traces;
* raw exception messages;
* HTTP details;
* payment provider debug messages;
* secret names.

---

## 10. Rate Limits

## 10.1. Purpose

Rate limits protect:

* Telegram bot responsiveness;
* Quiz Bank API quota;
* payment flow integrity;
* admin endpoints;
* database writes;
* abuse-sensitive actions.

## 10.2. User Action Rate Limits

Rate limits should exist for:

| Action | Purpose |
|---|---|
| `/start` or onboarding spam | Prevent duplicate setup pressure. |
| answer callbacks | Prevent duplicate answer writes. |
| training start | Prevent API request bursts. |
| retry after API error | Prevent retry storms. |
| payment start | Prevent invoice spam. |
| paywall click | Prevent duplicate payment attempts. |

## 10.3. Admin Rate Limits

Admin endpoints should have stricter controls for:

* login attempts;
* metrics refresh;
* user-level lookup;
* export actions;
* operational retry actions.

## 10.4. API Rate Limits

Quiz Bank API client should enforce:

* timeout;
* bounded retries;
* circuit breaker;
* per-user request control;
* global request control, if supported by infrastructure.

## 10.5. Rate Limit Behavior

Rate limit hit must:

* not corrupt session state;
* not create duplicate answers;
* not start duplicate payments;
* show safe German user-facing copy where needed;
* log technical context without secrets.

Rate limit hit should not be counted as learning failure.

---

## 11. Backup

## 11.1. Backup Scope

Production backup must cover data needed to restore:

* users;
* training sessions;
* training session items;
* question references;
* user answers;
* progress topics;
* progress history;
* mistakes;
* mistake history;
* subscriptions;
* payments;
* daily limits;
* analytics events, if stored internally;
* API error logs, if needed for incident review.

## 11.2. Backup Protection

Backups must be protected as sensitive data.

Required controls:

* encrypted storage;
* restricted access;
* no public bucket/container;
* no secrets printed in backup logs;
* backup credentials stored outside repository;
* restore access limited to authorized operators.

## 11.3. Backup Frequency

Exact frequency is an operational configuration.

Minimum production expectation:

| Data | Backup Need |
|---|---|
| User and learning state | Regular backup. |
| Payments and subscriptions | High reliability backup. |
| Analytics events | Backup if internal analytics is source of truth. |
| Logs | Retention by incident policy, not necessarily full backup. |

## 11.4. Restore Rule

Backup is not valid until restore is tested.

Restore test should verify:

* users can be restored;
* progress topics remain consistent;
* mistakes and histories remain linked;
* payments are not duplicated;
* subscriptions are not credited twice;
* daily limits are not corrupted;
* secrets are not restored into logs or public output.

## 11.5. Backup Retention Rule

Backup retention must balance:

* operational recovery;
* payment audit needs;
* privacy minimization;
* storage cost;
* incident investigation.

Exact retention period is not defined in this product document and must be set in production operations policy.

---

## 12. Secrets and Configuration

## 12.1. Secret Types

Sensitive configuration includes:

* Telegram bot token;
* Quiz Bank API key;
* payment provider credentials;
* database credentials;
* admin credentials;
* backup storage credentials;
* encryption keys;
* webhook signing secrets, if used.

## 12.2. Storage Rule

Secrets must be stored only in:

* environment variables; or
* protected secret storage.

Secrets must not be stored in:

* committed files;
* Markdown docs;
* analytics events;
* logs;
* Telegram callback data;
* client-visible UI.

## 12.3. Rotation Rule

Production must support secret rotation without code changes.

If a secret is suspected leaked:

1. revoke or rotate the secret;
2. invalidate affected sessions or tokens if relevant;
3. review logs for exposure;
4. document the incident;
5. verify service recovery.

---

## 13. Data Access Rules

## 13.1. Ownership Rule

Every user-scoped read or write must enforce ownership.

Examples:

* user can access only own sessions;
* user can access only own progress;
* user can access only own mistakes;
* user can use only own subscription state;
* payment credit must match payment owner.

## 13.2. Paid Access Rule

Paid features require:

```text
subscription.status = active
AND current_time < expires_at
AND payment.status = credited
```

Pending payment or pending subscription does not unlock paid access.

## 13.3. Admin Override Rule

Manual access override is not part of Release 1 product flow.

If future admin override is added, it must require:

* explicit authorization;
* reason code;
* audit log;
* expiration or reversal policy.

---

## 14. Incident Rules

## 14.1. Security Incident Examples

Security incident includes:

* leaked Telegram bot token;
* leaked Quiz Bank API key;
* unauthorized admin access;
* duplicated paid access from payment replay;
* logs containing secrets;
* public backup exposure;
* user data exposed to another user;
* raw payment payload exposed in UI.

## 14.2. Response Rule

Incident handling must:

1. stop active exposure;
2. preserve necessary audit evidence;
3. rotate affected secrets;
4. check data impact;
5. verify recovery;
6. document root cause and prevention.

---

## 15. Security Test Requirements

Release 1 should have tests or review checks for:

| Check | Expected Result |
|---|---|
| Duplicate Telegram update | No duplicate answer or payment. |
| API key logging | API key never appears in logs. |
| Payment duplicate event | No duplicate subscription credit. |
| Admin endpoint without auth | Request denied. |
| User accesses another user's progress | Request denied. |
| User accesses another user's payment | Request denied. |
| Quiz Bank invalid response | Rejected before use. |
| Analytics with secret field | Event rejected or redacted. |
| Backup restore | Data restored without duplicate payment credit. |
| Rate limit hit | No corrupted session or duplicate payment. |

---

## 16. Acceptance Criteria

Security and Privacy standard is acceptable for Release 1 if:

1. Telegram user ID has storage, logging and forbidden-use rules.
2. Personal data is minimized.
3. Email, phone and address are not required for basic use.
4. Payment data excludes credentials and raw provider secrets.
5. Payment credit is idempotent.
6. Quiz Bank API key is server-side only.
7. API responses are validated before use.
8. Admin endpoints require authentication and authorization.
9. Logs exclude secrets, raw credentials and sensitive payload dumps.
10. Rate limits protect user actions, admin endpoints and API calls.
11. Backups are encrypted, access-controlled and restore-tested.
12. Secrets are stored outside committed files.
13. User ownership is checked for user-scoped data.
14. Paid access requires credited payment and active subscription.

---

## 17. Security Invariants

1. Telegram user ID identifies a user but is not a secret.
2. Personal data is collected only when needed for product function.
3. User-scoped data requires ownership checks.
4. API keys never reach Telegram or user-facing UI.
5. Payment success does not equal access until credit is applied.
6. One payment cannot credit access twice.
7. Admin endpoints are privileged surfaces.
8. Logs are diagnostic records, not raw data archives.
9. Rate limits must not corrupt learning state.
10. Backups are sensitive data.
11. Restore must not duplicate payment or subscription state.
12. Secrets never appear in logs, analytics, committed files or Telegram messages.

