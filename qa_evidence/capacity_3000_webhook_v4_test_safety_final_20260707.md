# capacity_3000_webhook_v4 test safety final

Status: PASS

Source evidence:
- `qa_evidence/capacity_3000_webhook_v4_test_safety_rerun_20260707.json`
- `qa_evidence/capacity_3000_webhook_v4_test_safety_summary_20260707.json`

Checks:
- `scripts/local_ci.sh`: PASS
- Full `3000 concurrent webhook` gate: PASS

Capacity gate result:
- Accepted: `3000/3000`
- HTTP errors / 500: `0 / 0`
- HTTP p95 / p99: `406.385 ms / 598.04 ms`
- Lost events: `0`
- Duplicate update answers: `0`
- Duplicate quiz answers: `0`
- Persisted answers: `3000`
- Outbox missing / bad status: `0 / 0`
- DLQ total: `0`
- Webhook queue drained: `true`
- Answer persistence queue drained: `true`
- Webhook processing lag p95: `568.0 ms`
- Answer persistence processing lag p95: `2485.0 ms`
- PgBouncer `max_cl_waiting`: `0.0`
- Postgres lock waits: `0`
- Remaining `dtb-load*` containers after gate: `0`

Notes:
- Postgres lock sampler reported `errors: 1`, but lock-wait counters stayed at `0`: `max_lock_waiting_backends=0`, `max_ungranted_locks=0`, `lock_wait_rows=0`, `blocking_chain_rows=0`.
- The rerun evidence captured a dirty worktree because the new regression tests were intentionally uncommitted during the pre-commit capacity gate.
