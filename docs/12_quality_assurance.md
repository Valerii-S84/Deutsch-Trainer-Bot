# Deutsch Trainer Bot — Quality Assurance

## 1. Document Purpose

Цей документ описує стандарт перевірки якості **Deutsch Trainer Bot**.

Він фіксує:

* тести логіки прогресу;
* тести сесій;
* тести підписок;
* тести платежів;
* тести API;
* тести UX-кнопок;
* regression checklist;
* release quality gates.

Документ не є кодом тестів, test runner configuration або CI/CD специфікацією.

Його мета — задати строгий, перевірюваний і презентаційно зрозумілий QA standard, який можна перетворити на unit tests, integration tests, contract tests, end-to-end scenarios і release checklist.

---

## 2. QA Standard

Quality Assurance описаний у строгому академічному форматі.

У межах цього документа **Stanford-level standard** означає:

* кожна критична бізнес-логіка має test coverage;
* кожен lifecycle має happy path і failure path tests;
* кожен idempotency rule має duplicate-event test;
* кожна зовнішня інтеграція має contract і failure tests;
* кожен user-facing flow має UX button tests;
* кожен paywall і payment flow має safety tests;
* кожна regression checklist item має expected result;
* release не вважається готовим без проходження critical QA gates.

Головний принцип:

> Тести мають доводити, що бот не створює фальшивий прогрес, не губить навчальні дані й не відкриває платний доступ без підтвердження.

---

## 3. QA Scope

## 3.1. In Scope

Release 1 QA покриває:

* onboarding and first user flow;
* level and theme selection;
* training sessions;
* answer processing;
* progress calculation;
* mistake creation and repeat;
* daily limits;
* subscription access;
* Telegram Stars payments;
* Quiz Bank API integration;
* UX buttons and callback safety;
* analytics event creation;
* security-critical checks;
* regression checklist.

## 3.2. Out of Scope

Цей документ не визначає:

* конкретний test framework;
* programming language;
* CI provider;
* browser/device matrix beyond Telegram UX rules;
* load testing targets;
* penetration test procedure;
* production monitoring implementation.

---

## 4. Test Levels

| Level | Purpose |
|---|---|
| Unit tests | Перевірити чисті правила: progress formulas, status transitions, access rules. |
| Integration tests | Перевірити взаємодію сервісів: answer → progress → mistake → analytics. |
| Contract tests | Перевірити Quiz Bank API payloads and errors. |
| End-to-end tests | Перевірити user flows через bot handlers/callbacks. |
| Regression tests | Перевірити, що core flows не зламались після змін. |
| Security checks | Перевірити auth, ownership, secrets, duplicate events. |

## 4.1. Test Data Rule

Test data має бути:

* мінімальним;
* явно позначеним як test fixture;
* достатнім для сценарію;
* не копією production Quiz Bank;
* без real secrets;
* без real payment credentials;
* без реальних персональних даних.

## 4.2. Release Gate Implementation

Milestone 13 QA gates виконуються через:

```bash
python scripts/qa_release_gates.py --environment local --evidence-file qa_evidence/local_release_gates.json
```

Runner є модульним gate registry, а не монолітним тестовим скриптом.
Кожен gate має:

* stable `gate_id`;
* окремий scope;
* явну команду без shell interpolation;
* прив'язку до QA category;
* `critical` status.

Перед запуском release gate план перевіряється командою:

```bash
python scripts/qa_release_gates.py --check-plan
```

`scripts/local_ci.sh` виконує `--check-plan`, щоб registry не розійшовся з
фактичними файлами тестів. Повний release запуск не підміняє local CI: він
створює QA evidence для release decision.

GitHub CI запускає повний release runner для pull request, push до `main` і
manual `workflow_dispatch`. CI піднімає PostgreSQL і Redis service containers,
щоб migration/runtime gates не були лише локальними smoke scripts. Це означає,
що critical QA gates є CI blocker, а JSON evidence і coverage artifact
завантажуються як workflow artifacts.

Live Telegram, protected Quiz Bank і Telegram Stars sandbox gates виконуються
окремим manual workflow `Staging Integration Gates`, тому що вони потребують
protected secrets і зовнішнього sandbox evidence.

Partial gate runs allowed only for debugging. Якщо виконано не всі critical
gates, evidence отримує `gate_coverage = partial`, `result = blocked` і
`release_blocked = true`.

Якщо failed critical gates приймаються власником як risk, evidence має містити
явні поля `accepted_by`, `reason` і `accepted_at`; без цього failed gate блокує
release. Output у evidence редагується від secret-like values перед записом.

## 4.3. Critical Gate Matrix

| Gate ID | QA categories | Evidence |
|---|---|---|
| `python-integrity` | release evidence | `compileall app tests scripts` |
| `static-policy` | release evidence | explicit lint/type policy check |
| `secret-scan` | security, release evidence | tracked-file secret scan |
| `dependency-security-audit` | dependency audit, security audit, security, release evidence | `pip-audit` plus Bandit |
| `structure-limits` | structure limits, release evidence | file/function/class/parameter/nesting limits with legacy baseline |
| `docker-build-config` | Docker, release evidence | default/dev/production Compose config plus Docker build |
| `db-migration-smoke` | database migrations, release evidence | Alembic head plus PostgreSQL runtime schema check |
| `redis-runtime-smoke` | Redis runtime, release evidence | live Redis ping and ephemeral read/write |
| `progress-logic` | progress formulas, topic status, recommendation | progress model/service/repository/integration tests |
| `answer-to-analytics-flow` | answer → progress → mistake → analytics | training session, progress, mistakes and analytics tests |
| `telegram-flows` | Telegram flow, paywall, subscription, payment, buttons | handler, keyboard and router tests |
| `quiz-bank-contract-failures` | API contract, API failure | Quiz Bank client/schema/service tests |
| `payment-subscription` | payment idempotency, subscription lifecycle, access rules | entitlements, payment and subscription tests |
| `security-abuse` | ownership, admin, secrets, logs, rate limits | security, admin, DB model and foundation tests |
| `german-copy` | German-only copy | static user-facing copy tests |
| `qa-gate-runner` | release evidence | gate registry and evidence contract tests |
| `release-regression` | regression, coverage | full pytest suite with branch coverage threshold |

Release cannot be approved if any critical gate fails unless the responsible
owner explicitly accepts the failure in release evidence.

Coverage threshold is configured in `pyproject.toml` and currently blocks below
76% branch coverage for `app/`. The threshold is set from the current measured
baseline and should only move upward with matching tests.

Dependency audit has a narrow known exception for CVE-2026-34993 and
CVE-2026-47265 while the latest available `aiogram` release requires
`aiohttp<3.14` and the available fixes require `aiohttp>=3.14`. The exception
must be removed as soon as an `aiogram` release allows the fixed `aiohttp`.

Security note for the current exception:

* CVE-2026-34993 is only accepted because runtime code does not use
  `aiohttp.CookieJar` or `CookieJar.load()` with any input.
* CVE-2026-47265 is only accepted because runtime code does not pass
  per-request `cookies=` to `aiohttp` requests.
* Quiz Bank access uses `httpx.AsyncClient` with explicit auth headers and does
  not use `aiohttp` or cookies.
* Telegram API access uses the default `aiogram` `AiohttpSession`; audited
  `aiogram` source creates `ClientSession` with connector and headers only, and
  uses `post(..., data=..., timeout=...)` / `get(..., headers=..., timeout=...)`
  without `cookies=`.
* `scripts/security_audit.py` enforces this runtime assumption by scanning
  `app/` and installed `aiogram/client/` for `CookieJar`, `.load(` and
  `cookies=`. If that check fails, the exception is no longer safe; mitigation
  is to remove the affected usage, pass cookie data through an explicit
  `Cookie` header only where safe, or replace/override the Telegram HTTP
  session until `aiohttp>=3.14` is supported.

---

## 5. Progress Logic Tests

## 5.1. Purpose

Progress tests доводять, що система чесно рахує знання користувача по:

* accuracy;
* coverage;
* stability;
* weakness;
* recency;
* topic status;
* recommendation priority.

## 5.2. Accuracy Tests

| Case | Expected Result |
|---|---|
| 0 answers | Accuracy confidence is `none`; topic status stays `new`. |
| 1 correct answer | Accuracy increases, confidence remains low. |
| 4 correct answers | Accuracy may be high, but topic cannot be `strong`. |
| 8 correct from 10 answers | `accuracy_score = 80`. |
| Duplicate answer | Accuracy does not change twice. |

## 5.3. Coverage Tests

| Case | Expected Result |
|---|---|
| Same item answered twice | `unique_items_seen` increases once. |
| 12 unique items from 120 available | `coverage_score = 10`. |
| `available_items_count` unknown | `coverage_status = unknown`. |
| Coverage unknown | Topic cannot be `strong`. |
| Quiz Bank count changes | Progress recalculates and writes Progress History. |

## 5.4. Stability Tests

| Case | Expected Result |
|---|---|
| Correct repeat same day | Stability improves less than cross-day repeat. |
| Correct repeats on two different days | Stability increases meaningfully. |
| Wrong answer after improvement | Stability decreases. |
| Mistake review correct answer | Stability may increase only if answer is correct. |
| Old topic with no practice | Recency risk increases. |

## 5.5. Weakness Tests

| Case | Expected Result |
|---|---|
| Wrong answer | Weakness increases. |
| Repeated wrong answer | Weakness increases more. |
| Unresolved mistakes | Weakness remains above low. |
| Resolved mistakes | Weakness decreases. |
| High accuracy but repeated mistakes | Topic can still be `weak`. |

## 5.6. Topic Status Tests

| Case | Expected Result |
|---|---|
| Fewer than minimum answers | `topic_status = new`. |
| Low accuracy | `topic_status = weak`. |
| Good accuracy but low stability | `topic_status = learning` or `stable`, not `strong`. |
| High accuracy, coverage, stability and confidence | `topic_status = strong`. |
| Repeated mistakes with high accuracy | `weak` overrides positive signals. |

## 5.7. Recommendation Tests

| Case | Expected Result |
|---|---|
| 3+ active mistakes | Recommendation type is `repeat_mistakes`. |
| Weakness >= threshold | Recommendation targets weak topic. |
| Daily limit hit | Recommendation may be `upgrade_plan`. |
| API content unavailable | Recommendation does not point to unavailable topic. |
| Insufficient data | Recommendation asks for short exercise or baseline practice. |

## 5.8. Progress History Tests

| Case | Expected Result |
|---|---|
| Accepted answer updates progress | Progress History record is created. |
| Mistake created | Progress History records weakness change. |
| Mistake resolved | Progress History records stability/weakness change. |
| Recalculation without new answer | History event has `status_recalculated` or equivalent reason. |
| Duplicate answer | No duplicate Progress History. |

---

## 6. Session Tests

## 6.1. Purpose

Session tests доводять, що тренування створюється, триває, завершується і не приймає некоректні відповіді.

## 6.2. Session Lifecycle Tests

| Case | Expected Result |
|---|---|
| Start regular training | Training Session created with `session_type = regular`. |
| First question shown | Training Session Item moves to `shown`. |
| User answers all shown questions | Session moves to `completed`. |
| User presses Home during session | Session moves to `abandoned` by policy. |
| API failure before first question | Session does not create fake answer or charge limit. |
| Completed session receives answer callback | Answer is rejected or ignored safely. |

## 6.3. Answer Processing Tests

| Case | Expected Result |
|---|---|
| Correct answer | User Answer saved; session counters update; progress updates. |
| Wrong answer | User Answer saved; Mistake created or updated. |
| Duplicate Telegram update | No second User Answer. |
| Duplicate button tap | No second progress update. |
| Answer for unshown item | Rejected. |
| Answer from another user | Rejected by ownership rule. |

## 6.4. Daily Limit Tests

| Case | Expected Result |
|---|---|
| Question shown | Daily Limit charged once. |
| Answer duplicate | Daily Limit not charged again. |
| API failure before question shown | Daily Limit not charged. |
| Expired callback | Daily Limit not charged. |
| Free limit reached | Training blocked and daily limit paywall shown. |
| Plus user | Plus limit applies. |
| Pro user | Pro limit applies. |

## 6.5. Result Tests

| Case | Expected Result |
|---|---|
| Completed session | Result Screen can be shown. |
| Result shown | `result_shown` event recorded. |
| Session with mistakes | Result can offer mistake repeat. |
| Session with no mistakes | Positive no-mistake state appears. |
| API failure session | Result is not shown as completed session result. |

---

## 7. Mistake Tests

## 7.1. Mistake Creation Tests

| Case | Expected Result |
|---|---|
| First wrong answer | Mistake created with `status = new`. |
| Wrong answer on existing active mistake | `mistake_count` increments. |
| Wrong answer after `resolved` | Mistake reopens as `repeated`. |
| Duplicate wrong answer callback | Mistake does not increment twice. |
| Quiz item unavailable | Mistake preserved with content unavailable handling. |

## 7.2. Mistake Repeat Tests

| Case | Expected Result |
|---|---|
| Start mistake review with active mistakes | Session type is `mistake_review`. |
| Correct repeat once | Mistake becomes or remains `improved`, not `resolved`. |
| 3 correct repeats across 2 days | Mistake becomes `resolved`. |
| Wrong after `improved` | Mistake becomes `repeated`. |
| Wrong after `resolved` | Mistake becomes `repeated`. |

## 7.3. Mistake History Tests

| Case | Expected Result |
|---|---|
| Mistake created | Mistake History event `created`. |
| Wrong again | Mistake History event `wrong_again`. |
| Correct repeat | Mistake History event `correct_repeat`. |
| Resolved | Mistake History event `resolved`. |
| Reopened | Mistake History event `reopened`. |

---

## 8. Subscription Tests

## 8.1. Purpose

Subscription tests доводять, що Free, Plus і Pro access працюють без втрати навчальних даних.

## 8.2. Plan Access Tests

| Case | Expected Result |
|---|---|
| Free user opens basic training | Allowed under Free limit. |
| Free user opens short progress | Allowed. |
| Free user opens full progress | Paywall shown after allowed value moment. |
| Free user opens paid mistake repeat | Limited access or paywall by config. |
| Plus active opens full progress | Allowed. |
| Plus active repeats mistakes | Allowed. |
| Pro active opens Pro-only stats | Allowed if feature exists. |
| Pending subscription opens paid feature | Blocked. |

## 8.3. Subscription Lifecycle Tests

| Case | Expected Result |
|---|---|
| Payment credited for Plus | Subscription becomes `active`. |
| Current time < `expires_at` | Paid entitlements available. |
| Current time >= `expires_at` | Subscription becomes or behaves as `expired`. |
| Expired paid user trains | Free access applies. |
| Expired paid user data | Progress, mistakes and payments remain stored. |
| Renew after expiration | New access period activates without duplicate old credit. |

## 8.4. Entitlement Tests

| Case | Expected Result |
|---|---|
| Plus includes Free | All Free features available to Plus. |
| Pro includes Plus | All Plus features available to Pro. |
| Free limit < Plus limit < Pro limit | Limit hierarchy holds. |
| Missing entitlement | Paywall shown only if paywall moment allowed. |

---

## 9. Payment Tests

## 9.1. Purpose

Payment tests доводять, що Telegram Stars payment flow безпечний, idempotent і не відкриває доступ без підтвердження.

## 9.2. Payment Lifecycle Tests

| Case | Expected Result |
|---|---|
| User starts payment | Payment record created before invoice. |
| Provider confirms payment | Payment moves to `paid`. |
| Access credited | Payment moves to `credited`; Subscription active. |
| Payment failed | Payment moves to `failed`; no paid access. |
| Payment cancelled | Payment moves to `cancelled`; no paid access. |
| Payment pending | Paid feature remains blocked. |

## 9.3. Idempotency Tests

| Case | Expected Result |
|---|---|
| Duplicate provider event | No second subscription period. |
| Duplicate payment callback | No duplicate `payment_succeeded` effect. |
| Same provider payment id repeated | Payment is not credited twice. |
| Payment retry after failure | New valid Payment can be created by policy. |
| Renewal event | Does not duplicate old payment credit. |

## 9.4. Payment Security Tests

| Case | Expected Result |
|---|---|
| Provider event user mismatch | Payment rejected. |
| Provider event amount mismatch | Payment rejected. |
| Provider event plan mismatch | Payment rejected. |
| Raw provider secret in log attempt | Redacted or rejected. |
| Payment failure copy | User sees safe German message. |

---

## 10. API Tests

## 10.1. Purpose

API tests доводять, що Quiz Bank integration працює без дублювання контенту й без втрати стану при failures.

## 10.2. Contract Tests

| Test | Expected Result |
|---|---|
| Health response validation | `status` parsed and handled. |
| Levels contract | Only A1, A2, B1, B2, C1 accepted for Release 1. |
| Themes contract | Required theme fields present. |
| Availability contract | `available_items_count` parsed. |
| Question batch contract | Required question fields present. |
| Question lookup contract | Item can be fetched by `item_id`. |
| Metadata contract | Required progress metadata present. |
| Invalid JSON | Response rejected safely. |
| Missing required field | Response rejected safely. |

## 10.3. API Failure Tests

| Case | Expected Result |
|---|---|
| Timeout | User sees API error state; daily limit not charged. |
| Network error | User sees safe retry state. |
| 401/403 | Admin alert/log; no user retry loop with secrets. |
| 429 | Bounded retry or safe backoff. |
| 5xx | Retry policy or API Error State. |
| Invalid response | Payload rejected before use. |
| Insufficient questions | Configured policy applied. |
| API unavailable before question shown | No User Answer, no Mistake, no progress update. |

## 10.4. Cache and Fallback Tests

| Case | Expected Result |
|---|---|
| Valid theme cache | Theme selection can use cache. |
| Expired cache | Live API required or safe unavailable state. |
| Availability unknown | Coverage becomes `unknown`. |
| Full local question bank attempt | Not allowed. |
| Generated fake question attempt | Not allowed. |
| Cached session item already shown | Not shown twice unless idempotent flow requires same state. |

## 10.5. API Security Tests

| Case | Expected Result |
|---|---|
| API key in log attempt | Redacted or rejected. |
| Raw API response to user | Blocked. |
| Telegram PII sent to Quiz Bank | Blocked unless explicitly required. |
| Invalid item level | Item rejected. |
| Item theme mismatch | Item rejected for regular session. |

---

## 11. UX Button Tests

## 11.1. Purpose

UX button tests доводять, що Telegram buttons ведуть у правильні screens, не створюють duplicate state і не обходять access rules.

## 11.2. Global Button Tests

| Button | Expected Result |
|---|---|
| `▶️ Üben` | Starts or resumes Training Session safely. |
| `🎯 Niveau & Thema` | Opens Level/Theme flow. |
| `📊 Mein Fortschritt` | Opens Progress Screen. |
| `🔁 Fehler wiederholen` | Opens Mistake Screen or allowed paywall. |
| `▶️ Fehler üben` | Starts `mistake_review` session if allowed. |
| `🏠 Hauptmenü` | Opens Home and safely abandons active session if needed. |
| `↩️ Zurück` | Returns to previous valid screen. |
| `🔄 Noch einmal versuchen` | Retries only safe failed action. |
| `⭐ Plus ansehen` | Opens Paywall or Subscription flow. |
| `⭐ Plus aktivieren` | Opens Subscription Screen for Plus. |
| `🚀 Pro ansehen` | Opens Subscription Screen for Pro. |

## 11.3. Expired or Unknown Callback Tests

| Case | Expected Result |
|---|---|
| Expired answer button | No duplicate answer; safe message or current screen. |
| Unknown callback data | Safe fallback to Home. |
| Button from another user context | Rejected by ownership rule. |
| Repeated paywall click | No duplicate payment unless explicit retry. |
| Payment retry button | Creates new payment only by policy. |

## 11.4. German Copy Tests

| Case | Expected Result |
|---|---|
| Home screen | User-facing text German. |
| Training screen | Question wrapper and buttons German. |
| Result screen | Feedback German. |
| Progress screen | Progress labels German. |
| Mistake screen | Mistake copy German. |
| Paywall screen | Paywall copy German. |
| Subscription screen | Payment copy German. |
| Error states | Error messages German. |

## 11.5. UX Flow Tests

| Flow | Expected Result |
|---|---|
| Home → Üben → Training | Session starts. |
| Result → Progress | Progress opens. |
| Result → Fehler wiederholen | Mistake flow or paywall opens. |
| Progress → Üben | Training starts with valid context. |
| Mistake Screen → Fehler üben | Mistake review starts. |
| Paywall → Plus aktivieren | Subscription screen opens. |
| Subscription → payment success | Success state shown after confirmed payment. |
| Payment failure | Failure state shown; no access activated. |

---

## 12. Analytics QA Tests

| Case | Expected Result |
|---|---|
| First start | `bot_started` and possibly `user_created`. |
| Level selected | `level_selected`. |
| Training started | `training_started`. |
| Question answered | `question_answered`. |
| Training completed | `training_completed`. |
| Result shown | `result_shown`. |
| Progress opened | `progress_opened`. |
| Paywall shown | `paywall_shown` with context. |
| Paywall clicked | `paywall_clicked` attributable to shown paywall. |
| Payment success | `payment_succeeded` and `subscription_started`. |
| Analytics write failure | User flow continues. |
| Analytics payload with secret | Rejected or redacted. |

---

## 13. Security QA Tests

| Case | Expected Result |
|---|---|
| User accesses another user's progress | Denied. |
| User accesses another user's payment | Denied. |
| Admin endpoint without auth | Denied. |
| API key logging attempt | Secret not logged. |
| Payment credentials in analytics | Event rejected or redacted. |
| Rate limit hit | No duplicate answer or payment. |
| Backup restore test | Restored data does not duplicate payment credit. |

---

## 14. Regression Checklist

## 14.1. Core User Flow

Before release, verify:

* `/start` creates or recognizes user;
* level selection works;
* theme selection shows only available themes;
* training starts from `▶️ Üben`;
* question comes from Quiz Bank API;
* answer buttons accept one answer only;
* result screen appears after completion;
* user can return to Home safely.

## 14.2. Progress Regression

Verify:

* correct answer increases accuracy;
* wrong answer decreases accuracy and increases weakness;
* duplicate answer does not change progress twice;
* coverage uses unique item IDs;
* coverage unknown prevents `strong`;
* topic status respects weak override;
* Progress History is created.

## 14.3. Mistake Regression

Verify:

* wrong answer creates Mistake;
* repeated wrong answer increments `mistake_count`;
* one correct repeat does not resolve Mistake;
* repeated correct reviews across days can resolve Mistake;
* wrong after resolved reopens Mistake;
* Mistake History is created;
* no-mistake state is user-friendly.

## 14.4. Session and Limit Regression

Verify:

* shown question creates Training Session Item;
* Daily Limit charges once per shown question;
* API failure before question shown does not charge limit;
* expired callback does not charge limit;
* Free limit hit shows paywall;
* Plus/Pro limits are higher than Free.

## 14.5. Subscription Regression

Verify:

* Free user can use Free features;
* Free user sees paywall for paid features only at allowed moments;
* Plus user can open full progress;
* Plus user can repeat mistakes;
* Pro includes Plus;
* expired subscription returns to Free access;
* expiration does not delete learning data.

## 14.6. Payment Regression

Verify:

* Payment record is created before invoice;
* payment success moves Payment to `paid`;
* credited payment activates Subscription;
* duplicate provider event does not duplicate access;
* failed payment does not activate access;
* payment failure copy is German;
* payment logs contain no secrets.

## 14.7. API Regression

Verify:

* API timeout shows safe error;
* API timeout does not create answer;
* API timeout does not charge limit;
* insufficient questions policy works;
* invalid API item is rejected;
* unavailable item does not break mistake review;
* cache fallback respects TTL;
* bot does not duplicate full Quiz Bank.

## 14.8. UX Button Regression

Verify:

* all primary buttons route correctly;
* duplicate answer buttons are ignored after answer;
* expired buttons do not corrupt state;
* unknown callback returns to safe state;
* Home button is always available where required;
* Paywall buttons open expected subscription flow;
* all user-facing copy is German.

## 14.9. Analytics Regression

Verify:

* activation events are recorded;
* session completion events are recorded;
* progress usage events are recorded;
* mistake repeat events are recorded;
* paywall shown/clicked events include metadata;
* payment and subscription events are not duplicated;
* analytics events contain no secrets.

## 14.10. Security Regression

Verify:

* user ownership checks are enforced;
* admin endpoints require auth;
* API keys are not logged;
* payment credentials are not logged;
* rate limits prevent duplicate pressure;
* backup restore does not duplicate payments.

---

## 15. Release Quality Gates

Release 1 cannot be marked ready unless:

1. Core user flow passes.
2. Progress logic tests pass.
3. Session tests pass.
4. Mistake tests pass.
5. Subscription tests pass.
6. Payment idempotency tests pass.
7. API contract and failure tests pass.
8. UX button tests pass.
9. German copy checks pass.
10. Regression checklist is completed.
11. Security-critical checks pass.
12. Dependency/security audit passes except explicitly documented known
    dependency exceptions.
13. Docker config/build, PostgreSQL migration smoke and Redis runtime smoke pass
    in CI or the tested release environment.
14. Known failed tests are explicitly documented and accepted.
15. `scripts/qa_release_gates.py` evidence exists for the tested environment.
16. Staging/live integration workflow evidence exists before external release
    approval.

---

## 16. QA Evidence Standard

For each test run, record:

| Field | Purpose |
|---|---|
| `test_scope` | What was tested. |
| `environment` | Local, staging, CI, etc. |
| `build_or_commit` | Version under test, if available. |
| `result` | `passed`, `failed`, `blocked` or `accepted_with_failures`. |
| `release_blocked` | Whether release must remain blocked. |
| `gate_coverage` | Full or partial critical gate coverage. |
| `failed_cases` | Failed scenario list. |
| `known_risks` | Remaining risks. |
| `tested_at` | Timestamp. |

If no implementation stack exists yet, QA evidence can be a documentation traceability review.

For the current Python implementation, release QA evidence is JSON generated by
`scripts/qa_release_gates.py`. The evidence file must stay inside the repository
workspace and must not contain secrets, raw provider payloads or production data.
Local evidence is not sufficient to prove external staging/production facts such
as live Telegram Stars, webhook registration or production deployment health.

---

## 17. Acceptance Criteria

Quality Assurance standard is acceptable for Release 1 if:

1. Progress logic test categories are defined.
2. Session test categories are defined.
3. Subscription test categories are defined.
4. Payment test categories are defined.
5. API contract and failure tests are defined.
6. UX button tests are defined.
7. Analytics and security QA tests are defined.
8. Regression checklist covers core flows.
9. Release quality gates are explicit.
10. Test data rules prevent production content, secrets and real personal data in fixtures.
11. Release gate runner maps every Milestone 13 critical category to executable tests.
12. QA evidence can be generated with scope, environment, build/commit, result, failures, risks and timestamp.

---

## 18. QA Invariants

1. Duplicate events must not create duplicate learning or payment state.
2. API failure must not create fake progress.
3. One correct repeat must not resolve a mistake.
4. One payment must not credit access twice.
5. Subscription expiration must not delete learning data.
6. UX buttons must not bypass access rules.
7. User-facing copy must be German.
8. Test fixtures must not contain secrets or real personal data.
9. Regression checklist is required before Release 1.
10. Failed critical tests block release unless explicitly accepted as risk.
