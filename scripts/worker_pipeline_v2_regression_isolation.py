from __future__ import annotations

import argparse
import asyncio
import contextlib
import contextvars
import json
import math
import os
import subprocess
import sys
import threading
import time
import traceback
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

try:
    import resource as _resource
except ModuleNotFoundError:
    _resource = None
import asyncpg
from redis.asyncio import Redis
from sqlalchemy import insert
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


USER_COUNT = 100_000
DEFAULT_SESSION_COUNT = 5_000
DEFAULT_TARGET_RPS = 100
DEFAULT_TOTAL_REQUESTS = 500
DEFAULT_ARRIVAL_MODE = "steady"
DEFAULT_BURST_WINDOW_SECONDS = 1.0
DEFAULT_BURST_INTERVAL_SECONDS = 5.0
ARRIVAL_MODE_BURST = "burst"
DEFAULT_SESSION_SELECTION = "unique"
SESSION_SELECTION_HOTSET = "hotset"
DEFAULT_HOT_SESSION_RATIO = 0.0
DEFAULT_HOT_SESSION_POOL_SIZE = 100
SESSION_SELECTION_BUCKETS = 1_000
DEFAULT_CPU_PROFILE_INTERVAL_MS = 10.0
ERROR_SAMPLE_LIMIT = 5
CPU_PROFILE_TOPN = 20
SEED_BATCH_SIZE = 5_000
APP_NAME = "dtb_regression_isolation"
CATALOG_ID = "dtb-evidence-20260701"
CATALOG_VERSION = "2026-07-01-evidence"
ITEM_ID = "q_regular"
ITEM_VERSION = "1.0"
QUESTION_REFERENCE_ID = 1
QUESTION_TEXT = "Was ist korrekt?"
THEME = "Alltag"
THEME_KEY = "T01"
THEME_ID = "T01"
LEVEL = "A1"
AVAILABLE_ITEMS_COUNT = 599
CORRECT_ANSWER = "a2"
SELECTED_ANSWER = "a1"
QUESTION_OPTIONS = (
    {"option_id": "a1", "text": "Antwort A"},
    {"option_id": "a2", "text": "Antwort B"},
)

def current_max_rss_mb() -> float:
    return 0.0 if _resource is None else float(_resource.getrusage(_resource.RUSAGE_SELF).ru_maxrss) / 1024.0


@dataclass
class RequestMetrics:
    request_id: int
    session_id: int
    telegram_user_id: int
    update_id: int
    accepted: bool = False
    duplicate: bool = False
    error_type: str | None = None
    error_message: str | None = None
    error_traceback: str | None = None
    total_ms: float = 0.0
    queue_wait_ms: float = 0.0
    db_acquire_wait_ms: float = 0.0
    sql_count: int = 0
    connection_checkouts: int = 0
    session_opens: int = 0
    redis_calls: Counter[str] = field(default_factory=Counter)
    redis_latency_ms: dict[str, float] = field(default_factory=lambda: defaultdict(float))
    payload_build_ms: float = 0.0
    json_serialize_ms: float = 0.0
    payload_size_bytes: int = 0
    outbox_insert_ms: float = 0.0
    connection_hold_ms: float = 0.0
    timing_spans_ms: dict[str, float] = field(default_factory=dict)
    sql_statements: list[str] = field(default_factory=list)


@dataclass
class RuntimeStats:
    total_checkouts: int = 0
    max_checked_out: int = 0
    current_checked_out: int = 0
    app_pool_status_samples: list[dict[str, int | float | str]] = field(default_factory=list)
    worker_pool_status_samples: list[dict[str, int | float | str]] = field(default_factory=list)
    max_pending: int = 0
    max_processing: int = 0
    max_worker_lag_seconds: float = 0.0
    max_pg_total_connections: int = 0
    max_pg_active_connections: int = 0
    max_pg_waiting_connections: int = 0
    pg_wait_events_at_max_waiting: list[dict[str, object]] = field(default_factory=list)
    max_cpu_percent: float = 0.0
    max_rss_mb: float = 0.0
    open_sessions: int = 0
    max_open_sessions: int = 0
    current_in_flight_requests: int = 0
    max_in_flight_requests: int = 0


@dataclass(frozen=True)
class ArrivalProfile:
    mode: str
    target_rps: float
    burst_window_seconds: float | None = None
    burst_interval_seconds: float | None = None

    def target_offset_seconds(self, request_id: int) -> float:
        nominal_offset = request_id / self.target_rps
        if self.mode != ARRIVAL_MODE_BURST:
            return nominal_offset
        assert self.burst_window_seconds is not None
        assert self.burst_interval_seconds is not None
        interval_index = math.floor(nominal_offset / self.burst_interval_seconds)
        interval_started = interval_index * self.burst_interval_seconds
        interval_offset = nominal_offset - interval_started
        return interval_started + (interval_offset * (self.burst_window_seconds / self.burst_interval_seconds))

    def metadata(self, total_requests: int) -> dict[str, object]:
        scheduled_dispatch_span_sec = 0.0
        if total_requests > 1:
            scheduled_dispatch_span_sec = round(self.target_offset_seconds(total_requests - 1), 3)

        metadata: dict[str, object] = {
            "scheduler": "open_loop",
            "mode": self.mode,
            "target_rps": self.target_rps,
            "scheduled_dispatch_span_sec": scheduled_dispatch_span_sec,
            "burst_window_seconds": None,
            "burst_interval_seconds": None,
            "peak_rate_multiplier": 1.0,
            "estimated_peak_rps": round(self.target_rps, 3),
            "estimated_requests_per_full_interval": None,
        }
        if self.mode == ARRIVAL_MODE_BURST:
            assert self.burst_window_seconds is not None
            assert self.burst_interval_seconds is not None
            peak_rate_multiplier = self.burst_interval_seconds / self.burst_window_seconds
            metadata.update(
                {
                    "burst_window_seconds": self.burst_window_seconds,
                    "burst_interval_seconds": self.burst_interval_seconds,
                    "peak_rate_multiplier": round(peak_rate_multiplier, 3),
                    "estimated_peak_rps": round(self.target_rps * peak_rate_multiplier, 3),
                    "estimated_requests_per_full_interval": round(
                        self.target_rps * self.burst_interval_seconds,
                        3,
                    ),
                }
            )
        return metadata


@dataclass(frozen=True)
class SessionSelectionProfile:
    mode: str
    session_offset: int
    seeded_session_count: int
    total_requests: int
    hot_session_ratio: float = 0.0
    hot_session_pool_size: int = 0

    def session_id(self, request_id: int) -> int:
        if self.mode != SESSION_SELECTION_HOTSET:
            return self.session_offset + request_id + 1
        if self._is_hot_request(request_id):
            hot_request_index = self._hot_request_count_before(request_id)
            return self.session_offset + (hot_request_index % self.hot_session_pool_size) + 1
        unique_request_index = request_id - self._hot_request_count_before(request_id)
        return self.session_offset + self.hot_session_pool_size + unique_request_index + 1

    def required_seeded_sessions(self) -> int:
        if self.mode != SESSION_SELECTION_HOTSET:
            return self.session_offset + self.total_requests
        unique_requests = self.total_requests - self._hot_request_count_before(self.total_requests)
        return self.session_offset + self.hot_session_pool_size + unique_requests

    def metadata(self) -> dict[str, object]:
        repeated_requests = 0
        if self.mode == SESSION_SELECTION_HOTSET:
            repeated_requests = self._hot_request_count_before(self.total_requests)
        unique_requests = self.total_requests - repeated_requests
        return {
            "mode": self.mode,
            "session_offset": self.session_offset,
            "seeded_session_count": self.seeded_session_count,
            "hot_session_ratio": self.hot_session_ratio if self.mode == SESSION_SELECTION_HOTSET else 0.0,
            "hot_session_pool_size": self.hot_session_pool_size if self.mode == SESSION_SELECTION_HOTSET else 0,
            "repeated_request_count": repeated_requests,
            "unique_request_count": unique_requests,
            "required_seeded_sessions": self.required_seeded_sessions(),
        }

    def _is_hot_request(self, request_id: int) -> bool:
        if self.mode != SESSION_SELECTION_HOTSET:
            return False
        return (request_id % SESSION_SELECTION_BUCKETS) < self._hot_threshold()

    def _hot_request_count_before(self, request_id: int) -> int:
        if self.mode != SESSION_SELECTION_HOTSET:
            return 0
        full_cycles, remainder = divmod(request_id, SESSION_SELECTION_BUCKETS)
        hot_threshold = self._hot_threshold()
        return (full_cycles * hot_threshold) + min(remainder, hot_threshold)

    def _hot_threshold(self) -> int:
        return int(round(self.hot_session_ratio * SESSION_SELECTION_BUCKETS))


class CpuStackSampler:
    def __init__(self, *, interval_ms: float) -> None:
        self._interval_seconds = max(interval_ms, 1.0) / 1000.0
        self._main_thread_id = threading.main_thread().ident
        self._leaf_counts: Counter[str] = Counter()
        self._stack_counts: Counter[str] = Counter()
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._run, name="cpu-stack-sampler", daemon=True)
        self._samples = 0

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> dict[str, object]:
        self._stop_event.set()
        self._thread.join(timeout=5.0)
        return {
            "sampler": "main_thread_stack_sampling",
            "sample_interval_ms": round(self._interval_seconds * 1000.0, 3),
            "sample_count": self._samples,
            "top_leaf_frames": self._top_counts(self._leaf_counts),
            "top_stacks": self._top_counts(self._stack_counts),
        }

    def _run(self) -> None:
        if self._main_thread_id is None:
            return
        while not self._stop_event.is_set():
            frame = sys._current_frames().get(self._main_thread_id)
            if frame is not None:
                stack = traceback.extract_stack(frame)
                if stack:
                    self._leaf_counts[self._frame_label(stack[-1])] += 1
                    self._stack_counts[self._stack_label(stack)] += 1
                    self._samples += 1
            time.sleep(self._interval_seconds)

    def _top_counts(self, counts: Counter[str]) -> list[dict[str, object]]:
        total = max(self._samples, 1)
        return [
            {
                "label": label,
                "samples": count,
                "share": round(count / total, 4),
            }
            for label, count in counts.most_common(CPU_PROFILE_TOPN)
        ]

    @staticmethod
    def _frame_label(frame_summary: traceback.FrameSummary) -> str:
        return f"{Path(frame_summary.filename).name}:{frame_summary.name}:{frame_summary.lineno}"

    @classmethod
    def _stack_label(cls, stack: list[traceback.FrameSummary]) -> str:
        return " | ".join(cls._frame_label(frame) for frame in stack[-8:])


CURRENT_REQUEST: contextvars.ContextVar[RequestMetrics | None] = contextvars.ContextVar("CURRENT_REQUEST", default=None)


def percentile(values: list[float | int], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(float(value) for value in values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * p)))
    return round(ordered[index], 3)


def summarize_numeric(values: list[float | int]) -> dict[str, float]:
    return {
        "p50": percentile(values, 0.50),
        "p95": percentile(values, 0.95),
        "p99": percentile(values, 0.99),
        "max": round(max((float(v) for v in values), default=0.0), 3),
        "median": percentile(values, 0.50),
    }


def sample_pool_state(label: str, pool) -> dict[str, int | float | str]:
    return {
        "label": label,
        "pool_class": pool.__class__.__name__,
        "size": _pool_int_metric(pool, "size"),
        "checked_out": _pool_int_metric(pool, "checkedout"),
        "checked_in": _pool_int_metric(pool, "checkedin"),
        "overflow": _pool_int_metric(pool, "overflow"),
        "timestamp": round(time.perf_counter(), 6),
        "status": _pool_status(pool),
    }


def _pool_int_metric(pool, method_name: str) -> int:
    method = getattr(pool, method_name, None)
    if not callable(method):
        return 0
    try:
        return int(method())
    except TypeError:
        return 0


def _pool_status(pool) -> str:
    method = getattr(pool, "status", None)
    if not callable(method):
        return pool.__class__.__name__
    return str(method())


def build_arrival_profile(args: argparse.Namespace) -> ArrivalProfile:
    if args.target_rps <= 0:
        raise SystemExit("--target-rps must be greater than 0")
    if args.total_requests <= 0:
        raise SystemExit("--total-requests must be greater than 0")
    if args.arrival_mode != ARRIVAL_MODE_BURST:
        return ArrivalProfile(mode=args.arrival_mode, target_rps=args.target_rps)
    if args.burst_window_seconds <= 0:
        raise SystemExit("--burst-window-seconds must be greater than 0")
    if args.burst_interval_seconds <= 0:
        raise SystemExit("--burst-interval-seconds must be greater than 0")
    if args.burst_window_seconds > args.burst_interval_seconds:
        raise SystemExit("--burst-window-seconds must be less than or equal to --burst-interval-seconds")
    return ArrivalProfile(
        mode=args.arrival_mode,
        target_rps=args.target_rps,
        burst_window_seconds=args.burst_window_seconds,
        burst_interval_seconds=args.burst_interval_seconds,
    )


def build_session_selection_profile(args: argparse.Namespace) -> SessionSelectionProfile:
    session_offset = getattr(args, "session_offset", 0)
    seeded_session_count = getattr(args, "seeded_session_count", DEFAULT_SESSION_COUNT)
    if session_offset < 0:
        raise SystemExit("--session-offset must be greater than or equal to 0")
    if seeded_session_count <= 0:
        raise SystemExit("--seeded-session-count must be greater than 0")

    mode = getattr(args, "session_selection", DEFAULT_SESSION_SELECTION)
    if mode != SESSION_SELECTION_HOTSET:
        profile = SessionSelectionProfile(
            mode=DEFAULT_SESSION_SELECTION,
            session_offset=session_offset,
            seeded_session_count=seeded_session_count,
            total_requests=args.total_requests,
        )
    else:
        hot_session_ratio = float(getattr(args, "hot_session_ratio", DEFAULT_HOT_SESSION_RATIO))
        hot_session_pool_size = int(getattr(args, "hot_session_pool_size", DEFAULT_HOT_SESSION_POOL_SIZE))
        if hot_session_ratio < 0 or hot_session_ratio > 1:
            raise SystemExit("--hot-session-ratio must be between 0 and 1")
        if hot_session_pool_size <= 0:
            raise SystemExit("--hot-session-pool-size must be greater than 0")
        profile = SessionSelectionProfile(
            mode=SESSION_SELECTION_HOTSET,
            session_offset=session_offset,
            seeded_session_count=seeded_session_count,
            total_requests=args.total_requests,
            hot_session_ratio=hot_session_ratio,
            hot_session_pool_size=hot_session_pool_size,
        )

    if profile.required_seeded_sessions() > seeded_session_count:
        raise SystemExit("configured session selection exceeds seeded session capacity")
    return profile


def answer_payload(*, session_id: int, question_token: str, training_session_item_id: int) -> dict[str, object]:
    return {
        "session_id": session_id,
        "question_token": question_token,
        "question_id": ITEM_ID,
        "question_text": QUESTION_TEXT,
        "answer_options": list(QUESTION_OPTIONS),
        "correct_answer": CORRECT_ANSWER,
        "explanation": "Richtig erklaert.",
        "position": 1,
        "total_questions": 5,
        "level": LEVEL,
        "theme": THEME,
        "correct_answer_text": "Antwort B",
        "theme_key": THEME_KEY,
        "content_version": ITEM_VERSION,
        "metadata_snapshot": {
            "catalog_id": CATALOG_ID,
            "theme_id": THEME_ID,
            "progress_theme_key": "alltag",
            "content_version": ITEM_VERSION,
            "available_items_count": AVAILABLE_ITEMS_COUNT,
        },
        "question_reference_id": QUESTION_REFERENCE_ID,
        "training_session_item_id": training_session_item_id,
        "user_id": session_id,
        "telegram_user_id": 7_000_000_000 + session_id,
        "session_type": "regular",
        "answered_count": 0,
        "correct_answers": 0,
    }


def measurement_update_id(run_base: int, offset: int) -> int:
    return run_base + offset


def measurement_session_id(
    session_offset: int,
    request_id: int,
    *,
    session_selection_profile: SessionSelectionProfile | None = None,
) -> int:
    if session_selection_profile is not None:
        return session_selection_profile.session_id(request_id)
    return session_offset + request_id + 1


def resolve_max_in_flight(args: argparse.Namespace, settings) -> int | None:
    override = getattr(args, "max_in_flight", None)
    if override is not None:
        if override <= 0:
            raise SystemExit("--max-in-flight must be greater than 0")
        return override
    backend = getattr(settings, "db_connection_backend", None)
    backend_value = getattr(backend, "value", backend)
    if backend_value == "pgbouncer_transaction":
        return int(settings.effective_bot_in_flight_limit)
    return None


def collect_error_samples(requests: list[RequestMetrics], *, limit: int = ERROR_SAMPLE_LIMIT) -> list[dict[str, object]]:
    samples: list[dict[str, object]] = []
    for metrics in requests:
        if not metrics.error_type:
            continue
        samples.append(
            {
                "request_id": metrics.request_id,
                "session_id": metrics.session_id,
                "error_type": metrics.error_type,
                "error_message": metrics.error_message,
                "traceback": metrics.error_traceback,
            }
        )
        if len(samples) >= limit:
            break
    return samples


def database_url() -> str:
    value = os.environ.get("DATABASE_URL")
    if not value:
        raise SystemExit("DATABASE_URL is required")
    return value


def redis_url() -> str:
    value = os.environ.get("REDIS_URL")
    if not value:
        raise SystemExit("REDIS_URL is required")
    return value


def current_commit() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    except Exception:
        return "unknown"


def current_branch() -> str:
    try:
        return subprocess.check_output(["git", "branch", "--show-current"], text=True).strip() or "detached"
    except Exception:
        return "unknown"


from scripts.worker_pipeline_v2_runtime import run_scenario, seed_database


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Worker Pipeline V2 regression isolation helpers.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    seed = subparsers.add_parser("seed")
    seed.add_argument("--session-count", type=int, default=DEFAULT_SESSION_COUNT)
    seed.set_defaults(func=seed_database)

    run = subparsers.add_parser("run")
    _add_run_arguments(run)
    run.set_defaults(func=run_scenario)
    return parser


def _add_run_arguments(run: argparse.ArgumentParser) -> None:
    run.add_argument("--workers-on", action="store_true")
    run.add_argument("--target-rps", type=float, default=DEFAULT_TARGET_RPS)
    run.add_argument("--total-requests", type=int, default=DEFAULT_TOTAL_REQUESTS)
    run.add_argument("--session-offset", type=int, default=0)
    run.add_argument("--seeded-session-count", type=int, default=DEFAULT_SESSION_COUNT)
    run.add_argument(
        "--max-in-flight",
        type=int,
        default=None,
        help="Optional cap for concurrently executing requests inside the harness.",
    )
    run.add_argument(
        "--arrival-mode",
        choices=[DEFAULT_ARRIVAL_MODE, ARRIVAL_MODE_BURST],
        default=DEFAULT_ARRIVAL_MODE,
        help="steady keeps the current open-loop schedule; burst compresses each open-loop interval into a shorter window.",
    )
    run.add_argument(
        "--burst-window-seconds",
        type=float,
        default=DEFAULT_BURST_WINDOW_SECONDS,
        help="Active dispatch window per burst when --arrival-mode=burst.",
    )
    run.add_argument(
        "--burst-interval-seconds",
        type=float,
        default=DEFAULT_BURST_INTERVAL_SECONDS,
        help="Full burst interval when --arrival-mode=burst. Example: 5/1 or 5/2 with 100 RPS dispatches 500 requests in about 1-2 seconds.",
    )
    run.add_argument(
        "--session-selection",
        choices=[DEFAULT_SESSION_SELECTION, SESSION_SELECTION_HOTSET],
        default=DEFAULT_SESSION_SELECTION,
        help="unique uses one session_id per request; hotset reuses a bounded pool for a configurable request share.",
    )
    run.add_argument(
        "--hot-session-ratio",
        type=float,
        default=DEFAULT_HOT_SESSION_RATIO,
        help="Fraction of requests that should reuse the hot session pool when --session-selection=hotset.",
    )
    run.add_argument(
        "--hot-session-pool-size",
        type=int,
        default=DEFAULT_HOT_SESSION_POOL_SIZE,
        help="Number of reusable session_ids in the hot pool when --session-selection=hotset.",
    )
    run.add_argument(
        "--cpu-profile-output",
        default=None,
        help="Optional JSON file path for sampled main-thread CPU profile output.",
    )
    run.add_argument(
        "--cpu-profile-interval-ms",
        type=float,
        default=DEFAULT_CPU_PROFILE_INTERVAL_MS,
        help="Sampling interval in milliseconds for --cpu-profile-output.",
    )


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    result = args.func(args)
    if asyncio.iscoroutine(result):
        asyncio.run(result)


if __name__ == "__main__":
    main()
