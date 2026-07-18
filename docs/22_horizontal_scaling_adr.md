# 22. Horizontal Scaling ADR

Date: `2026-07-02`
Status: `Accepted for this increment`

## Decision

Use **multi-instance webhook ingress** for bot update handling, plus a
**separate outbox worker pool**, instead of introducing a new internal
ingestion queue in this increment.

Chosen model:

`Telegram webhook -> local/load-balancer ingress -> N stateless app webhook replicas -> PostgreSQL/PgBouncer + Redis -> M outbox worker replicas`

Key constraints:

- webhook registration must be done by **one** bootstrap path only;
- serving webhook traffic must be separated from webhook registration, so
  scaling `N` replicas does not call `delete_webhook()` /
  `set_webhook()` on every instance start;
- global admission control must move from per-process memory to shared
  Redis coordination;
- PgBouncer budget must be recomputed for `N app replicas + M worker replicas`;
- local disposable load evidence must exercise the real multi-instance
  webhook path, not only the direct service-level harness.

## Evidence

### 1. What `stash@{0}` actually contains

`stash@{0}` is **not** a separate ingestion architecture.

Evidence:

- tracked diff touches only:
  `app/repositories/answers.py`,
  `app/repositories/outbox.py`,
  `app/services/training_answer_fast_path.py`,
  `app/services/training_answer_flow.py`,
  `app/workers/outbox.py`,
  and tests around answer/outbox behavior;
- untracked stash parent contains only:
  `app/workers/outbox_batch.py`,
  `app/workers/outbox_payloads.py`;
- `app/workers/outbox_batch.py` is a PostgreSQL batch processor for
  progress/mistakes/analytics side effects after `answer.accepted`;
- no stash file introduces webhook ingress split, polling coordinator,
  Redis queue, broker consumer, or cross-process update dispatcher.

Conclusion:

- Worker Pipeline V2 is a **DB-side outbox processing optimization**;
- it is compatible in direction with horizontal scaling, but it does not
  by itself solve Telegram update ingestion scaling.

### 2. Current update-ingress model

Current runtime is dual-mode in code, but **production is locked to
webhook**:

- `app/main.py` starts webhook mode when
  `settings.webhook_mode_enabled`, otherwise polling when
  `settings.bot_polling_enabled`;
- `docker-compose.production.yml` sets
  `BOT_WEBHOOK_ENABLED=True` and `BOT_POLLING_ENABLED=False`;
- `docs/16_architecture_lock.md` locks production to
  `Hetzner VPS + Docker Compose + Caddy + HTTPS webhook`;
- `docs/20_operations_deployment_runbook.md` allows polling only as an
  explicit isolated exception, with **exactly one active bot process**.

Conclusion:

- current scalable path must align with webhook mode, not polling mode.

### 3. Telegram delivery model

Official Telegram documentation supports the webhook-based choice:

- Bot FAQ: there are only two update modes, long polling or webhook, and
  they are mutually exclusive:
  <https://core.telegram.org/bots/faq>
- Bot API: `setWebhook` supports `max_connections` for simultaneous HTTPS
  deliveries and states that `getUpdates` cannot be used while a webhook
  is set:
  <https://core.telegram.org/bots/api>

Inference from the official model:

- polling is a single shared update stream confirmed via `offset`, so
  scaling polling consumers for the same bot token is the wrong
  horizontal-scaling primitive;
- webhook delivery is the native Telegram mechanism that can fan updates
  into several concurrent HTTP requests, which matches an LB plus
  stateless replica model.

### 4. Current code already points toward multi-process webhook runtime

- `app/security/rate_limits.py` already has Redis-backed
  `RedisDuplicateUpdateGuard` explicitly described for multi-process
  webhook runtime;
- `docker-compose.production.yml` already separates `bot` and `worker`
  services, so the project already uses a split between request handling
  and durable post-processing.

### 5. Gaps that block trivial replica scaling today

- `app/main.py:198-205` performs `delete_webhook(drop_pending_updates=True)`
  and `set_webhook(...)` inside normal runtime startup, so blindly
  starting `N` webhook replicas would make every replica mutate Telegram
  webhook state;
- `app/bot/dispatcher.py` uses `settings.effective_bot_in_flight_limit`,
  but that value is still enforced per process only;
- current load harness runs
  `scripts/worker_pipeline_v2_regression_isolation.py`, which is a
  direct service-level benchmark and does not start real app replicas or
  a real ingress layer.

## Compatibility Decision for Worker Pipeline V2

**Rebase/merge V2 into the current branch. Do not discard it.**

Reason:

- V2 is not a competing ingress architecture;
- V2 optimizes the existing outbox worker plane and remains useful after
  horizontal scaling, especially when worker replicas increase;
- V2 must be rebased onto the current
  `app/db/session.py` PgBouncer/reuse behavior and the current Redis
  runtime changes, but there is no architectural conflict.

Non-goal:

- V2 must not be treated as proof that ingestion scaling is already
  solved.

## Resulting Scope for This Increment

1. Keep webhook as the scaling path.
2. Add a singleton webhook registration/bootstrap path and a separate
   webhook-serving runtime path for replicas.
3. Scale app webhook replicas horizontally behind local ingress/LB.
4. Keep and scale the outbox worker pool separately; rebase Worker
   Pipeline V2 there.
5. Replace per-process backpressure budget with shared Redis admission
   control.
6. Re-derive PgBouncer math for the total replica set.
7. Extend the disposable harness to start the real multi-instance stack
   and run both sustained and burst tests.

## Explicit Rejections

### Rejected for this increment: multi-process polling

Reason:

- conflicts with the production architecture lock;
- polling is documented as a different mutually exclusive mode and is
  only approved here as a singleton isolated exception;
- would require a new ingestion coordinator or queue just to compensate
  for using the non-production mode.

### Rejected for this increment: new internal Redis queue between ingress and app workers

Reason:

- not required to unlock the first horizontal-scaling step;
- duplicates responsibilities with the already existing durable outbox
  worker plane;
- adds a second queueing architecture before proving the simpler
  webhook-plus-replicas path.

This can be revisited only if the multi-instance webhook model still
fails after shared admission control, PgBouncer re-budgeting, and V2
worker improvements are measured.
