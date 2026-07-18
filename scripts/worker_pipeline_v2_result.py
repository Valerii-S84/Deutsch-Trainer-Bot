from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

import scripts.worker_pipeline_v2_runtime as runtime_root
from scripts.worker_pipeline_v2_runtime import *


def _environment(runner: Any) -> dict[str, Any]:
    settings = runner.settings
    return {
        "database_url_redacted": redact_url(database_url()),
        "redis_url_redacted": redact_redis_url(redis_url()),
        "db_connection_backend": str(getattr(settings.db_connection_backend, "value", settings.db_connection_backend)),
        "effective_bot_in_flight_limit": settings.effective_bot_in_flight_limit,
        "db_pool_size": settings.db_pool_size,
        "db_max_overflow": settings.db_max_overflow,
        "db_pool_timeout": settings.db_pool_timeout,
        "worker_db_pool_size": settings.worker_db_pool_size,
        "worker_db_max_overflow": settings.worker_db_max_overflow,
        "worker_db_pool_timeout": settings.worker_db_pool_timeout,
    }


def _request_summary(runner: Any, requests: list[RequestMetrics]) -> dict[str, Any]:
    errors = Counter(metrics.error_type for metrics in requests if metrics.error_type)
    return {
        "requested": runner.args.total_requests,
        "accepted": sum(1 for metrics in requests if metrics.accepted),
        "duplicates": sum(1 for metrics in requests if metrics.duplicate),
        "errors": sum(errors.values()),
        "error_types": {key: value for key, value in errors.items() if key},
        **runner.run_meta,
    }


def _request_metrics(requests: list[RequestMetrics]) -> dict[str, Any]:
    return {
        "latency_ms": summarize_numeric([metrics.total_ms for metrics in requests]),
        "queue_wait_ms": summarize_numeric([metrics.queue_wait_ms for metrics in requests]),
        "db_acquire_wait_ms": summarize_numeric([metrics.db_acquire_wait_ms for metrics in requests]),
        "transaction_hold_ms": summarize_numeric([metrics.connection_hold_ms for metrics in requests]),
        "sql_count_per_answer": summarize_numeric([metrics.sql_count for metrics in requests]),
        "connection_checkouts_per_answer": summarize_numeric(
            [metrics.connection_checkouts for metrics in requests]
        ),
        "session_opens_per_answer": summarize_numeric([metrics.session_opens for metrics in requests]),
        "redis_total_latency_ms": summarize_numeric(
            [sum(metrics.redis_latency_ms.values()) for metrics in requests]
        ),
        "redis_calls_total": dict(sum_counters(metrics.redis_calls for metrics in requests)),
        "outbox_insert_ms": summarize_numeric([metrics.outbox_insert_ms for metrics in requests]),
        "payload_build_ms": summarize_numeric([metrics.payload_build_ms for metrics in requests]),
        "json_serialize_ms": summarize_numeric([metrics.json_serialize_ms for metrics in requests]),
        "payload_size_bytes": summarize_numeric([metrics.payload_size_bytes for metrics in requests]),
        "timing_spans_p95_ms": summarize_spans(requests),
    }


def _harness(runner: Any, arrival: dict[str, Any]) -> dict[str, Any]:
    return {
        "open_loop_target_rps": runner.args.target_rps,
        "arrival_mode": arrival["mode"],
        "burst_window_seconds": arrival["burst_window_seconds"],
        "burst_interval_seconds": arrival["burst_interval_seconds"],
        "scheduled_dispatch_span_sec": arrival["scheduled_dispatch_span_sec"],
        "dispatch_gap_ms": runner.run_meta["dispatch_gap_ms"],
        "dispatch_lag_ms": runner.run_meta["dispatch_lag_ms"],
        "max_in_flight_limit": runner.max_in_flight_limit,
        "max_in_flight_requests": runner.run_meta["max_in_flight_requests"],
        "achieved_rps": runner.run_meta["achieved_rps"],
    }


def _pool_and_connections(runner: Any) -> dict[str, Any]:
    stats = runner.runtime_stats
    app_pool = runner.db_session_module._engine.sync_engine.pool
    worker_pool = runner.db_session_module._worker_engine.sync_engine.pool
    return {
        "pool": {
            "total_checkouts": stats.total_checkouts,
            "app_max_checked_out": stats.max_checked_out,
            "app_max_overflow": max((sample["overflow"] for sample in stats.app_pool_status_samples), default=0),
            "app_after": sample_pool_state("app", app_pool),
            "worker_after": sample_pool_state("worker", worker_pool),
        },
        "connections": {
            "pg_stat_activity_before": runner.before_pg,
            "pg_stat_activity_during_max": {
                "total": stats.max_pg_total_connections,
                "active": stats.max_pg_active_connections,
                "waiting": stats.max_pg_waiting_connections,
            },
            "pg_wait_events_at_max_waiting": stats.pg_wait_events_at_max_waiting,
            "pg_stat_activity_after_pre_dispose": runner.after_pg_pre_dispose,
            "pg_stat_activity_after_post_dispose": runner.after_pg_post_dispose,
            "before_pool": runner.before_pool,
        },
    }


async def _outbox_summary(runner: Any) -> dict[str, Any]:
    stats = runner.runtime_stats
    return {
        "before": runner.before_counts,
        "after": runner.after_counts,
        "max_pending": stats.max_pending,
        "max_processing": stats.max_processing,
        "drain_seconds": runner.drain_seconds,
        "max_worker_lag_seconds": stats.max_worker_lag_seconds,
        "duplicate_accepted_answer_groups": runner.duplicate_groups,
        "schema": await runner.outbox_schema(),
    }


def _write_cpu_profile(runner: Any) -> dict[str, Any] | None:
    output = runner.args.cpu_profile_output
    summary = runner.cpu_profile_holder.get("summary")
    if output and summary is not None:
        path = Path(output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(summary, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    if output is None:
        return None
    return {
        "output_path": output,
        "sample_interval_ms": runner.args.cpu_profile_interval_ms,
        "sample_count": (summary or {}).get("sample_count", 0),
        "top_leaf_frames": (summary or {}).get("top_leaf_frames", [])[:5],
    }


async def build_scenario_result(runner: Any) -> dict[str, Any]:
    requests = [
        metrics for request_id, metrics in runner.app_requests.items()
        if request_id < runner.args.total_requests
    ]
    arrival = runner.arrival_profile.metadata(runner.args.total_requests)
    stats = runner.runtime_stats
    result = {
        "commit": current_commit(),
        "branch": current_branch(),
        "workers_on": runner.args.workers_on,
        "env": _environment(runner),
        "seed": {
            "users": USER_COUNT,
            "active_sessions": runner.args.seeded_session_count,
            "pending_question_payloads": runner.args.seeded_session_count,
        },
        "single_request_probe": runner.single_probe,
        "requests": _request_summary(runner, requests),
        "error_samples": collect_error_samples(requests),
        "arrival": arrival,
        "session_selection": runner.session_selection_profile.metadata(),
        "harness_validation": _harness(runner, arrival),
        **_request_metrics(requests),
        **_pool_and_connections(runner),
        "outbox": await _outbox_summary(runner),
        "cpu_ram_approx": {
            "app_cpu_percent": round(stats.max_cpu_percent, 3),
            "app_max_rss_mb": round(stats.max_rss_mb, 3),
        },
        "cpu_profile": _write_cpu_profile(runner),
        "open_sessions_after_test": stats.open_sessions,
        "engine_disposed": True,
    }
    return result
