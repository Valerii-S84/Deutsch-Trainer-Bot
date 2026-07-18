from __future__ import annotations



from scripts import load_stabilization_orchestrator as _root
globals().update({name: value for name, value in vars(_root).items() if not name.startswith("__")})


def _percentile(values: Sequence[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * percentile)))
    return round(ordered[index], 3)


def _summarize_numeric(values: Sequence[float]) -> dict[str, float]:
    if not values:
        return {"count": 0, "p50": 0.0, "p95": 0.0, "p99": 0.0, "max": 0.0}
    return {
        "count": float(len(values)),
        "p50": _percentile(values, 0.50),
        "p95": _percentile(values, 0.95),
        "p99": _percentile(values, 0.99),
        "max": round(max(values), 3),
    }


def _scheduled_offset(index: int, *, target_rps: float, mode: str, burst_window: float, burst_interval: float) -> float:
    nominal_offset = index / target_rps
    if mode == "steady":
        return nominal_offset
    interval_index = math.floor(nominal_offset / burst_interval)
    interval_started = interval_index * burst_interval
    interval_offset = nominal_offset - interval_started
    return interval_started + (interval_offset * (burst_window / burst_interval))


def _measurement_session_id(session_offset: int, request_index: int) -> int:
    return session_offset + request_index + 1


def _build_answer_callback_update(
    update_id: int,
    *,
    session_id: int,
    telegram_user_id: int,
    selected_option_id: str,
) -> dict[str, Any]:
    question_token = f"tok{session_id:08d}"
    return {
        "update_id": update_id,
        "callback_query": {
            "id": f"cbq-{update_id}",
            "from": {
                "id": telegram_user_id,
                "is_bot": False,
                "first_name": "Load",
            },
            "chat_instance": f"chat-{session_id}",
            "message": {
                "message_id": update_id,
                "date": 1_720_000_000,
                "chat": {"id": telegram_user_id, "type": "private"},
                "from": {
                    "id": LOADTEST_BOT_USER_ID,
                    "is_bot": True,
                    "first_name": "LoadTestBot",
                    "username": "dtb_loadtest_bot",
                },
                "text": "load-harness-question",
            },
            "data": (
                f"{CALLBACK_TRAIN_ANSWER_PREFIX}:"
                f"{session_id}:{question_token}:{selected_option_id}"
            ),
        },
    }


POSTGRES_ACTIVITY_SQL = """
SELECT
    state,
    wait_event_type,
    wait_event,
    COUNT(*)::int AS count
FROM pg_stat_activity
WHERE datname = current_database()
  AND pid <> pg_backend_pid()
GROUP BY state, wait_event_type, wait_event
ORDER BY count DESC, state ASC, wait_event_type ASC, wait_event ASC
"""

POSTGRES_WAITING_ACTIVITY_SQL = r"""
SELECT
    pid,
    application_name,
    state,
    wait_event_type,
    wait_event,
    ROUND(EXTRACT(EPOCH FROM (clock_timestamp() - COALESCE(query_start, state_change))) * 1000)::bigint AS age_ms,
    pg_blocking_pids(pid) AS blocking_pids,
    LEFT(regexp_replace(query, '\s+', ' ', 'g'), 240) AS query_sample
FROM pg_stat_activity
WHERE datname = current_database()
  AND pid <> pg_backend_pid()
  AND wait_event_type IS NOT NULL
ORDER BY age_ms DESC, pid ASC
LIMIT 25
"""

POSTGRES_LOCK_SUMMARY_SQL = """
WITH lock_rows AS (
    SELECT
        l.locktype,
        l.mode,
        l.granted,
        COALESCE(n.nspname || '.' || c.relname, l.relation::text, '<none>') AS relation,
        l.page,
        l.tuple
    FROM pg_locks AS l
    LEFT JOIN pg_database AS d ON d.oid = l.database
    LEFT JOIN pg_class AS c ON c.oid = l.relation
    LEFT JOIN pg_namespace AS n ON n.oid = c.relnamespace
    WHERE COALESCE(l.pid, 0) <> pg_backend_pid()
      AND (l.database IS NULL OR d.datname = current_database())
)
SELECT
    locktype,
    mode,
    granted,
    relation,
    page,
    tuple,
    COUNT(*)::int AS count
FROM lock_rows
GROUP BY locktype, mode, granted, relation, page, tuple
ORDER BY granted ASC, count DESC, locktype ASC, mode ASC, relation ASC
LIMIT 100
"""

POSTGRES_LOCK_WAITS_SQL = r"""
SELECT
    l.pid,
    a.application_name,
    a.state,
    a.wait_event_type,
    a.wait_event,
    l.locktype,
    l.mode,
    COALESCE(n.nspname || '.' || c.relname, l.relation::text, '<none>') AS relation,
    l.page,
    l.tuple,
    pg_blocking_pids(l.pid) AS blocking_pids,
    LEFT(regexp_replace(a.query, '\s+', ' ', 'g'), 240) AS waiting_query_sample
FROM pg_locks AS l
JOIN pg_stat_activity AS a ON a.pid = l.pid
LEFT JOIN pg_class AS c ON c.oid = l.relation
LEFT JOIN pg_namespace AS n ON n.oid = c.relnamespace
WHERE a.datname = current_database()
  AND NOT l.granted
ORDER BY a.query_start ASC NULLS LAST, l.pid ASC
LIMIT 50
"""
POSTGRES_BLOCKING_CHAINS_SQL = r"""
SELECT
    blocked.pid AS waiting_pid,
    blocker.pid AS blocking_pid,
    blocked.application_name AS waiting_application_name,
    blocker.application_name AS blocking_application_name,
    blocked.state AS waiting_state,
    blocker.state AS blocking_state,
    blocked.wait_event_type AS waiting_event_type,
    blocked.wait_event AS waiting_event,
    ROUND(EXTRACT(EPOCH FROM (clock_timestamp() - COALESCE(blocked.query_start, blocked.state_change))) * 1000)::bigint AS waiting_age_ms,
    ROUND(EXTRACT(EPOCH FROM (clock_timestamp() - COALESCE(blocker.query_start, blocker.state_change))) * 1000)::bigint AS blocking_age_ms,
    LEFT(regexp_replace(blocked.query, '\s+', ' ', 'g'), 240) AS waiting_query_sample,
    LEFT(regexp_replace(blocker.query, '\s+', ' ', 'g'), 240) AS blocking_query_sample
FROM pg_stat_activity AS blocked
JOIN LATERAL unnest(pg_blocking_pids(blocked.pid)) AS blocking_pid(pid) ON true
JOIN pg_stat_activity AS blocker ON blocker.pid = blocking_pid.pid
WHERE blocked.datname = current_database()
ORDER BY waiting_age_ms DESC, blocked.pid ASC
LIMIT 50
"""
