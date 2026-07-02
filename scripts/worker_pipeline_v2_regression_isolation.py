from __future__ import annotations

import argparse
import asyncio
import contextlib
import contextvars
import json
import os
import resource
import subprocess
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import asyncpg
from redis.asyncio import Redis
from sqlalchemy import insert
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


USER_COUNT = 100_000
SESSION_COUNT = 5_000
TARGET_RPS = 100
TOTAL_REQUESTS = 500
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
    total_ms: float = 0.0
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
    max_cpu_percent: float = 0.0
    max_rss_mb: float = 0.0
    open_sessions: int = 0
    max_open_sessions: int = 0


CURRENT_REQUEST: contextvars.ContextVar[RequestMetrics | None] = contextvars.ContextVar(
    "CURRENT_REQUEST",
    default=None,
)


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
    }


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


async def seed_database(_args: argparse.Namespace) -> None:
    from app.db.models import QuestionReference, QuizSession, TrainingSessionItem, User

    engine = create_async_engine(database_url(), future=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async with session_factory() as db:
        for start in range(1, USER_COUNT + 1, SEED_BATCH_SIZE):
            end = min(USER_COUNT + 1, start + SEED_BATCH_SIZE)
            rows = [
                {"id": user_id, "telegram_user_id": 7_000_000_000 + user_id}
                for user_id in range(start, end)
            ]
            await db.execute(insert(User), rows)
        await db.execute(
            insert(QuestionReference),
            [
                {
                    "id": QUESTION_REFERENCE_ID,
                    "catalog_id": CATALOG_ID,
                    "item_id": ITEM_ID,
                    "item_version": ITEM_VERSION,
                    "level": LEVEL,
                    "theme": THEME,
                    "theme_key": THEME_KEY,
                    "source": "local_quiz_catalog",
                    "metadata_snapshot": {
                        "catalog_id": CATALOG_ID,
                        "theme_id": THEME_ID,
                        "progress_theme_key": "alltag",
                        "content_version": ITEM_VERSION,
                    },
                    "content_version": ITEM_VERSION,
                    "question_text_snapshot": QUESTION_TEXT,
                    "correct_answer_snapshot": "Antwort B",
                    "explanation_snapshot": "Richtig erklaert.",
                }
            ],
        )

        quiz_rows: list[dict[str, object]] = []
        session_item_rows: list[dict[str, object]] = []
        for session_id in range(1, SESSION_COUNT + 1):
            question_token = f"tok{session_id:08d}"
            quiz_rows.append(
                {
                    "id": session_id,
                    "user_id": session_id,
                    "level": LEVEL,
                    "theme": THEME,
                    "session_type": "regular",
                    "status": "active",
                    "total_questions": 5,
                    "shown_questions_count": 1,
                    "answered_count": 0,
                    "correct_answers": 0,
                    "catalog_id": CATALOG_ID,
                    "catalog_version": CATALOG_VERSION,
                    "source": "local_quiz_catalog",
                    "source_metadata": {"theme_key": THEME_KEY},
                    "api_metadata": {
                        "pending_question": answer_payload(
                            session_id=session_id,
                            question_token=question_token,
                            training_session_item_id=session_id,
                        )
                    },
                }
            )
            session_item_rows.append(
                {
                    "id": session_id,
                    "session_id": session_id,
                    "user_id": session_id,
                    "question_reference_id": QUESTION_REFERENCE_ID,
                    "catalog_id": CATALOG_ID,
                    "item_id": ITEM_ID,
                    "item_version": ITEM_VERSION,
                    "position": 1,
                    "status": "shown",
                    "shown_at": datetime.now(UTC),
                }
            )
        await db.execute(insert(QuizSession), quiz_rows)
        await db.execute(insert(TrainingSessionItem), session_item_rows)
        await db.commit()

    await engine.dispose()
    print(
        json.dumps(
            {
                "seeded": {
                    "users": USER_COUNT,
                    "active_sessions": SESSION_COUNT,
                    "pending_question_payloads": SESSION_COUNT,
                    "question_references": 1,
                    "catalog_id": CATALOG_ID,
                }
            },
            indent=2,
        )
    )


async def run_scenario(args: argparse.Namespace) -> None:
    from sqlalchemy import event

    from app.db import session as db_session_module
    from app.db.session import AsyncSessionLocal, dispose_engine
    from app.repositories.outbox import (
        OUTBOX_DEAD,
        OUTBOX_DONE,
        OUTBOX_FAILED,
        OUTBOX_PENDING,
        OUTBOX_PROCESSING,
        OutboxRepository,
    )
    from app.runtime.redis import create_redis_client
    from app.runtime.timing import begin_timing, end_timing
    from app.security.rate_limits import ACTION_ANSWER, RedisDuplicateUpdateGuard, RedisRateLimiter
    from app.services import training_answer_fast_path as fast_path_module
    from app.services.training_answer_flow import TrainingAnswerProcessor
    from app.services.training_session import TrainingSessionService
    from app.workers.outbox import OutboxWorker

    settings = __import__("app.config", fromlist=["get_settings"]).get_settings()
    runtime_stats = RuntimeStats()
    app_requests: dict[int, RequestMetrics] = {}
    connection_requests: dict[int, int] = {}
    redis_client: RedisProbe | None = None
    worker_task: asyncio.Task[None] | None = None
    sampler_task: asyncio.Task[None] | None = None
    inspector_conn: asyncpg.Connection | None = None
    stop_event = asyncio.Event()
    single_probe_holder: dict[str, object] = {}
    duplicate_guard: RedisDuplicateUpdateGuard | None = None
    rate_limiter: RedisRateLimiter | None = None

    @contextlib.asynccontextmanager
    async def app_session_scope():
        runtime_stats.open_sessions += 1
        runtime_stats.max_open_sessions = max(runtime_stats.max_open_sessions, runtime_stats.open_sessions)
        try:
            async with AsyncSessionLocal() as db:
                yield db
        finally:
            runtime_stats.open_sessions = max(0, runtime_stats.open_sessions - 1)

    async def outbox_counts() -> dict[str, int]:
        assert inspector_conn is not None
        rows = await inspector_conn.fetch(
            """
            SELECT status, COUNT(*)::int AS count
            FROM outbox_events
            GROUP BY status
            """
        )
        counts = {
            OUTBOX_PENDING: 0,
            OUTBOX_PROCESSING: 0,
            OUTBOX_DONE: 0,
            OUTBOX_FAILED: 0,
            OUTBOX_DEAD: 0,
        }
        for status, count in rows:
            counts[str(status)] = int(count)
        return counts

    async def pending_lag_seconds() -> float:
        assert inspector_conn is not None
        value = await inspector_conn.fetchval(
            """
            SELECT COALESCE(
                EXTRACT(EPOCH FROM (NOW() - MIN(created_at))),
                0
            )
            FROM outbox_events
            WHERE status = 'pending'
            """
        )
        return round(float(value or 0.0), 3)

    async def duplicate_group_count() -> int:
        assert inspector_conn is not None
        value = await inspector_conn.fetchval(
            """
            SELECT COUNT(*)::int
            FROM (
                SELECT user_id, session_id, external_quiz_id
                FROM user_answers
                GROUP BY user_id, session_id, external_quiz_id
                HAVING COUNT(*) > 1
            ) groups
            """
        )
        return int(value or 0)

    async def pg_activity_snapshot() -> dict[str, int]:
        assert inspector_conn is not None
        row = await inspector_conn.fetchrow(
            """
            SELECT
                COUNT(*)::int AS total,
                COUNT(*) FILTER (WHERE state = 'active')::int AS active,
                COUNT(*) FILTER (WHERE wait_event_type IS NOT NULL)::int AS waiting
            FROM pg_stat_activity
            WHERE datname = current_database()
              AND application_name <> $1
            """,
            APP_NAME,
        )
        return {
            "total": int(row["total"]),
            "active": int(row["active"]),
            "waiting": int(row["waiting"]),
        }

    async def outbox_schema() -> dict[str, object]:
        assert inspector_conn is not None
        indexes = await inspector_conn.fetch(
            """
            SELECT indexname, indexdef
            FROM pg_indexes
            WHERE tablename = 'outbox_events'
            ORDER BY indexname
            """
        )
        triggers = await inspector_conn.fetch(
            """
            SELECT tgname
            FROM pg_trigger
            JOIN pg_class ON pg_trigger.tgrelid = pg_class.oid
            WHERE pg_class.relname = 'outbox_events'
              AND NOT pg_trigger.tgisinternal
            ORDER BY tgname
            """
        )
        constraints = await inspector_conn.fetch(
            """
            SELECT conname, contype
            FROM pg_constraint
            JOIN pg_class ON pg_constraint.conrelid = pg_class.oid
            WHERE pg_class.relname = 'outbox_events'
            ORDER BY conname
            """
        )
        return {
            "indexes": [dict(row) for row in indexes],
            "triggers": [dict(row) for row in triggers],
            "constraints": [dict(row) for row in constraints],
        }

    def pool_sample(label: str, pool) -> dict[str, int | float | str]:
        sample = {
            "label": label,
            "size": int(pool.size()),
            "checked_out": int(pool.checkedout()),
            "checked_in": int(pool.checkedin()),
            "overflow": int(pool.overflow()),
            "timestamp": round(time.perf_counter(), 6),
            "status": pool.status(),
        }
        return sample

    async def sampler() -> None:
        started_wall = time.perf_counter()
        started_cpu = time.process_time()
        try:
            while not stop_event.is_set():
                snapshot = await pg_activity_snapshot()
                runtime_stats.max_pg_total_connections = max(runtime_stats.max_pg_total_connections, snapshot["total"])
                runtime_stats.max_pg_active_connections = max(runtime_stats.max_pg_active_connections, snapshot["active"])
                runtime_stats.max_pg_waiting_connections = max(runtime_stats.max_pg_waiting_connections, snapshot["waiting"])

                counts = await outbox_counts()
                runtime_stats.max_pending = max(runtime_stats.max_pending, counts[OUTBOX_PENDING])
                runtime_stats.max_processing = max(runtime_stats.max_processing, counts[OUTBOX_PROCESSING])
                runtime_stats.max_worker_lag_seconds = max(runtime_stats.max_worker_lag_seconds, await pending_lag_seconds())

                app_pool = pool_sample("app", db_session_module._engine.sync_engine.pool)
                runtime_stats.app_pool_status_samples.append(app_pool)
                worker_pool = pool_sample("worker", db_session_module._worker_engine.sync_engine.pool)
                runtime_stats.worker_pool_status_samples.append(worker_pool)

                elapsed_wall = max(time.perf_counter() - started_wall, 0.001)
                elapsed_cpu = max(time.process_time() - started_cpu, 0.0)
                cpu_percent = (elapsed_cpu / elapsed_wall) * 100.0
                runtime_stats.max_cpu_percent = max(runtime_stats.max_cpu_percent, cpu_percent)
                runtime_stats.max_rss_mb = max(
                    runtime_stats.max_rss_mb,
                    float(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss) / 1024.0,
                )
                await asyncio.sleep(0.1)
        except asyncio.CancelledError:
            raise

    class RedisProbe:
        def __init__(self, client: Redis) -> None:
            self._client = client

        async def _record(self, method: str, operation) -> object:
            metrics = CURRENT_REQUEST.get()
            started = time.perf_counter()
            try:
                return await operation
            finally:
                if metrics is not None:
                    metrics.redis_calls[method] += 1
                    metrics.redis_latency_ms[method] += (time.perf_counter() - started) * 1000

        async def set(self, *args, **kwargs) -> object:
            return await self._record("set", self._client.set(*args, **kwargs))

        async def time(self, *args, **kwargs) -> object:
            return await self._record("time", self._client.time(*args, **kwargs))

        async def eval(self, *args, **kwargs) -> object:
            return await self._record("eval", self._client.eval(*args, **kwargs))

        async def flushdb(self) -> object:
            return await self._client.flushdb()

        async def aclose(self) -> None:
            await self._client.aclose()

    def request_token(request_id: int) -> contextvars.Token[RequestMetrics | None]:
        return CURRENT_REQUEST.set(app_requests[request_id])

    @event.listens_for(db_session_module._engine.sync_engine, "before_cursor_execute")
    def _before_cursor_execute(conn, cursor, statement, parameters, context, executemany) -> None:
        metrics = CURRENT_REQUEST.get()
        if metrics is None:
            return
        metrics.sql_count += 1
        if len(metrics.sql_statements) < 10:
            metrics.sql_statements.append(statement.strip())

    @event.listens_for(db_session_module._engine.sync_engine.pool, "checkout")
    def _checkout(dbapi_connection, connection_record, connection_proxy) -> None:
        runtime_stats.total_checkouts += 1
        runtime_stats.current_checked_out += 1
        runtime_stats.max_checked_out = max(runtime_stats.max_checked_out, runtime_stats.current_checked_out)
        metrics = CURRENT_REQUEST.get()
        if metrics is not None:
            metrics.connection_checkouts += 1
            connection_requests[id(connection_record)] = metrics.request_id
        connection_record.info["dtb_checkout_started"] = time.perf_counter()

    @event.listens_for(db_session_module._engine.sync_engine.pool, "checkin")
    def _checkin(dbapi_connection, connection_record) -> None:
        runtime_stats.current_checked_out = max(0, runtime_stats.current_checked_out - 1)
        started = connection_record.info.pop("dtb_checkout_started", None)
        request_id = connection_requests.pop(id(connection_record), None)
        if started is None or request_id is None:
            return
        metrics = app_requests.get(request_id)
        if metrics is not None:
            metrics.connection_hold_ms += (time.perf_counter() - started) * 1000

    original_fast_payload = fast_path_module._answer_accepted_payload
    original_fallback_payload = TrainingAnswerProcessor._answer_accepted_payload
    original_enqueue = OutboxRepository.enqueue

    def wrapped_fast_payload(*args, **kwargs):
        metrics = CURRENT_REQUEST.get()
        started = time.perf_counter()
        payload = original_fast_payload(*args, **kwargs)
        elapsed = (time.perf_counter() - started) * 1000
        if metrics is not None:
            metrics.payload_build_ms += elapsed
            if not metrics.payload_size_bytes:
                metrics.payload_size_bytes = len(json.dumps(payload, default=_json_default).encode("utf-8"))
        return payload

    def wrapped_fallback_payload(self, *args, **kwargs):
        metrics = CURRENT_REQUEST.get()
        started = time.perf_counter()
        payload = original_fallback_payload(self, *args, **kwargs)
        elapsed = (time.perf_counter() - started) * 1000
        if metrics is not None:
            metrics.payload_build_ms += elapsed
            if not metrics.payload_size_bytes:
                metrics.payload_size_bytes = len(json.dumps(payload, default=_json_default).encode("utf-8"))
        return payload

    async def wrapped_enqueue(self, db, *, event_type, aggregate_type, aggregate_id, idempotency_key, payload):
        metrics = CURRENT_REQUEST.get()
        if metrics is not None:
            started_serialize = time.perf_counter()
            payload_json = json.dumps(payload, default=_json_default)
            metrics.json_serialize_ms += (time.perf_counter() - started_serialize) * 1000
            metrics.payload_size_bytes = max(metrics.payload_size_bytes, len(payload_json.encode("utf-8")))
        started = time.perf_counter()
        result = await original_enqueue(
            self,
            db,
            event_type=event_type,
            aggregate_type=aggregate_type,
            aggregate_id=aggregate_id,
            idempotency_key=idempotency_key,
            payload=payload,
        )
        if metrics is not None:
            metrics.outbox_insert_ms += (time.perf_counter() - started) * 1000
        return result

    fast_path_module._answer_accepted_payload = wrapped_fast_payload
    TrainingAnswerProcessor._answer_accepted_payload = wrapped_fallback_payload
    OutboxRepository.enqueue = wrapped_enqueue

    async def single_request_probe(service: TrainingSessionService) -> dict[str, object]:
        request_id = 100_000
        session_id = SESSION_COUNT
        metrics = RequestMetrics(
            request_id=request_id,
            session_id=session_id,
            telegram_user_id=7_000_000_000 + session_id,
            update_id=9_900_000 + session_id,
        )
        app_requests[request_id] = metrics
        token = request_token(request_id)
        try:
            async with app_session_scope() as db:
                metrics.session_opens += 1
                timing, timing_token = begin_timing()
                connection_started = time.perf_counter()
                await db.connection()
                metrics.db_acquire_wait_ms = (time.perf_counter() - connection_started) * 1000
                try:
                    result = await service.submit_answer(
                        db,
                        metrics.telegram_user_id,
                        session_id=session_id,
                        question_token=f"tok{session_id:08d}",
                        selected_option_id=SELECTED_ANSWER,
                        telegram_update_id=metrics.update_id,
                    )
                    metrics.accepted = not result.is_duplicate
                    metrics.duplicate = result.is_duplicate
                finally:
                    end_timing(timing_token)
                metrics.timing_spans_ms = timing
                await db.rollback()
        finally:
            CURRENT_REQUEST.reset(token)
        return {
            "accepted": metrics.accepted,
            "duplicate": metrics.duplicate,
            "sql_count": metrics.sql_count,
            "sql_statements": metrics.sql_statements,
            "db_acquire_wait_ms": round(metrics.db_acquire_wait_ms, 3),
            "connection_checkouts": metrics.connection_checkouts,
            "connection_hold_ms": round(metrics.connection_hold_ms, 3),
            "payload_build_ms": round(metrics.payload_build_ms, 3),
            "json_serialize_ms": round(metrics.json_serialize_ms, 3),
            "payload_size_bytes": metrics.payload_size_bytes,
            "outbox_insert_ms": round(metrics.outbox_insert_ms, 3),
            "timing_spans_ms": {key: round(value, 3) for key, value in metrics.timing_spans_ms.items()},
        }

    async def invoke_request(service: TrainingSessionService, request_id: int) -> None:
        session_id = request_id + 1
        metrics = RequestMetrics(
            request_id=request_id,
            session_id=session_id,
            telegram_user_id=7_000_000_000 + session_id,
            update_id=9_100_000 + request_id,
        )
        app_requests[request_id] = metrics
        token = request_token(request_id)
        started = time.perf_counter()
        try:
            assert duplicate_guard is not None
            assert rate_limiter is not None
            accepted = await duplicate_guard.accept(metrics.update_id)
            if not accepted:
                metrics.duplicate = True
                return
            decision = await rate_limiter.check(action=ACTION_ANSWER, identity=f"user:{metrics.telegram_user_id}")
            if not decision.allowed:
                metrics.error_type = "RateLimited"
                metrics.error_message = f"retry_after={decision.retry_after_seconds}"
                return
            async with app_session_scope() as db:
                metrics.session_opens += 1
                timing, timing_token = begin_timing()
                connection_started = time.perf_counter()
                await db.connection()
                metrics.db_acquire_wait_ms = (time.perf_counter() - connection_started) * 1000
                try:
                    result = await service.submit_answer(
                        db,
                        metrics.telegram_user_id,
                        session_id=metrics.session_id,
                        question_token=f"tok{metrics.session_id:08d}",
                        selected_option_id=SELECTED_ANSWER,
                        telegram_update_id=metrics.update_id,
                    )
                    await db.commit()
                finally:
                    end_timing(timing_token)
                metrics.timing_spans_ms = timing
                metrics.accepted = not result.is_duplicate
                metrics.duplicate = result.is_duplicate
        except Exception as exc:
            metrics.error_type = exc.__class__.__name__
            metrics.error_message = str(exc)
        finally:
            metrics.total_ms = (time.perf_counter() - started) * 1000
            CURRENT_REQUEST.reset(token)

    async def load_run(service: TrainingSessionService) -> dict[str, object]:
        start = time.perf_counter()
        tasks: list[asyncio.Task[None]] = []
        for request_id in range(TOTAL_REQUESTS):
            target = start + (request_id / TARGET_RPS)
            now = time.perf_counter()
            if target > now:
                await asyncio.sleep(target - now)
            tasks.append(asyncio.create_task(invoke_request(service, request_id)))
        await asyncio.gather(*tasks)
        return {"request_duration_sec": round(time.perf_counter() - start, 3)}

    try:
        inspector_url = make_url(database_url()).set(query={"application_name": APP_NAME})
        inspector_dsn = inspector_url.render_as_string(hide_password=False).replace("+asyncpg", "")
        inspector_conn = await asyncpg.connect(inspector_dsn)

        redis_client = RedisProbe(create_redis_client(settings))
        await redis_client.flushdb()
        service = TrainingSessionService()
        duplicate_guard = RedisDuplicateUpdateGuard(redis_client, ttl_seconds=settings.telegram_duplicate_update_ttl_seconds)
        rate_limiter = RedisRateLimiter(redis_client)
        before_counts = await outbox_counts()
        before_pg = await pg_activity_snapshot()
        before_pool = pool_sample("app", db_session_module._engine.sync_engine.pool)
        single_probe_holder["probe"] = await single_request_probe(service)

        if args.workers_on:
            worker = OutboxWorker(session_factory=async_sessionmaker(
                db_session_module._worker_engine,
                expire_on_commit=False,
                class_=AsyncSession,
            ))
            worker_task = asyncio.create_task(worker.run_forever(idle_sleep_seconds=0.05))

        sampler_task = asyncio.create_task(sampler())
        run_meta = await load_run(service)
        stop_event.set()
        await asyncio.wait_for(sampler_task, timeout=5)

        drain_started = time.perf_counter()
        if args.workers_on:
            while True:
                counts = await outbox_counts()
                if counts[OUTBOX_PENDING] == 0 and counts[OUTBOX_PROCESSING] == 0:
                    break
                if time.perf_counter() - drain_started > 30:
                    break
                await asyncio.sleep(0.1)
        drain_seconds = round(time.perf_counter() - drain_started, 3) if args.workers_on else 0.0

        if worker_task is not None:
            worker_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await worker_task
            worker_task = None

        after_counts = await outbox_counts()
        after_pg_pre_dispose = await pg_activity_snapshot()
        duplicate_groups = await duplicate_group_count()
        await dispose_engine()
        after_pg_post_dispose = await pg_activity_snapshot()
        await redis_client.aclose()

        active_requests = [metrics for request_id, metrics in app_requests.items() if request_id < TOTAL_REQUESTS]
        accepted = sum(1 for metrics in active_requests if metrics.accepted)
        duplicates = sum(1 for metrics in active_requests if metrics.duplicate)
        errors = Counter(metrics.error_type for metrics in active_requests if metrics.error_type)
        error_count = sum(errors.values())

        result = {
            "commit": current_commit(),
            "branch": current_branch(),
            "workers_on": args.workers_on,
            "env": {
                "database_url_redacted": redact_url(database_url()),
                "redis_url_redacted": redact_redis_url(redis_url()),
                "db_pool_size": settings.db_pool_size,
                "db_max_overflow": settings.db_max_overflow,
                "db_pool_timeout": settings.db_pool_timeout,
                "worker_db_pool_size": settings.worker_db_pool_size,
                "worker_db_max_overflow": settings.worker_db_max_overflow,
                "worker_db_pool_timeout": settings.worker_db_pool_timeout,
            },
            "seed": {
                "users": USER_COUNT,
                "active_sessions": SESSION_COUNT,
                "pending_question_payloads": SESSION_COUNT,
            },
            "single_request_probe": single_probe_holder["probe"],
            "requests": {
                "requested": TOTAL_REQUESTS,
                "accepted": accepted,
                "duplicates": duplicates,
                "errors": error_count,
                "error_types": {key: value for key, value in errors.items() if key},
                **run_meta,
            },
            "latency_ms": summarize_numeric([metrics.total_ms for metrics in active_requests]),
            "db_acquire_wait_ms": summarize_numeric([metrics.db_acquire_wait_ms for metrics in active_requests]),
            "transaction_hold_ms": summarize_numeric([metrics.connection_hold_ms for metrics in active_requests]),
            "sql_count_per_answer": summarize_numeric([metrics.sql_count for metrics in active_requests]),
            "connection_checkouts_per_answer": summarize_numeric(
                [metrics.connection_checkouts for metrics in active_requests]
            ),
            "session_opens_per_answer": summarize_numeric([metrics.session_opens for metrics in active_requests]),
            "redis_total_latency_ms": summarize_numeric(
                [sum(metrics.redis_latency_ms.values()) for metrics in active_requests]
            ),
            "redis_calls_total": dict(sum_counters(metrics.redis_calls for metrics in active_requests)),
            "outbox_insert_ms": summarize_numeric([metrics.outbox_insert_ms for metrics in active_requests]),
            "payload_build_ms": summarize_numeric([metrics.payload_build_ms for metrics in active_requests]),
            "json_serialize_ms": summarize_numeric([metrics.json_serialize_ms for metrics in active_requests]),
            "payload_size_bytes": summarize_numeric([metrics.payload_size_bytes for metrics in active_requests]),
            "timing_spans_p95_ms": summarize_spans(active_requests),
            "pool": {
                "total_checkouts": runtime_stats.total_checkouts,
                "app_max_checked_out": runtime_stats.max_checked_out,
                "app_max_overflow": max((sample["overflow"] for sample in runtime_stats.app_pool_status_samples), default=0),
                "app_after": pool_sample("app", db_session_module._engine.sync_engine.pool),
                "worker_after": pool_sample("worker", db_session_module._worker_engine.sync_engine.pool),
            },
            "connections": {
                "pg_stat_activity_before": before_pg,
                "pg_stat_activity_during_max": {
                    "total": runtime_stats.max_pg_total_connections,
                    "active": runtime_stats.max_pg_active_connections,
                    "waiting": runtime_stats.max_pg_waiting_connections,
                },
                "pg_stat_activity_after_pre_dispose": after_pg_pre_dispose,
                "pg_stat_activity_after_post_dispose": after_pg_post_dispose,
                "before_pool": before_pool,
            },
            "outbox": {
                "before": before_counts,
                "after": after_counts,
                "max_pending": runtime_stats.max_pending,
                "max_processing": runtime_stats.max_processing,
                "drain_seconds": drain_seconds,
                "max_worker_lag_seconds": runtime_stats.max_worker_lag_seconds,
                "duplicate_accepted_answer_groups": duplicate_groups,
                "schema": await outbox_schema(),
            },
            "cpu_ram_approx": {
                "app_cpu_percent": round(runtime_stats.max_cpu_percent, 3),
                "app_max_rss_mb": round(runtime_stats.max_rss_mb, 3),
            },
            "open_sessions_after_test": runtime_stats.open_sessions,
            "engine_disposed": True,
        }
        print(json.dumps(result, indent=2, default=_json_default))
    finally:
        fast_path_module._answer_accepted_payload = original_fast_payload
        TrainingAnswerProcessor._answer_accepted_payload = original_fallback_payload
        OutboxRepository.enqueue = original_enqueue
        stop_event.set()
        if worker_task is not None:
            worker_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await worker_task
        if sampler_task is not None:
            sampler_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await sampler_task
        if redis_client is not None:
            with contextlib.suppress(Exception):
                await redis_client.aclose()
        if inspector_conn is not None:
            await inspector_conn.close()


def sum_counters(counters) -> Counter[str]:
    total: Counter[str] = Counter()
    for counter in counters:
        total.update(counter)
    return total


def summarize_spans(requests: list[RequestMetrics]) -> dict[str, float]:
    values: dict[str, list[float]] = defaultdict(list)
    for metrics in requests:
        for name, value in metrics.timing_spans_ms.items():
            values[name].append(value)
    return {name: percentile(items, 0.95) for name, items in sorted(values.items())}


def redact_url(value: str) -> str:
    parsed = make_url(value)
    safe = parsed.set(password="***")
    return safe.render_as_string(hide_password=False)


def redact_redis_url(value: str) -> str:
    if "@" not in value:
        return value
    prefix, suffix = value.rsplit("@", 1)
    if ":" not in prefix:
        return value
    return "***@" + suffix


def _json_default(value: object) -> object:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return str(value)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Worker Pipeline V2 regression isolation helpers.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    seed = subparsers.add_parser("seed")
    seed.set_defaults(func=seed_database)

    run = subparsers.add_parser("run")
    run.add_argument("--workers-on", action="store_true")
    run.set_defaults(func=run_scenario)
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    result = args.func(args)
    if asyncio.iscoroutine(result):
        asyncio.run(result)


if __name__ == "__main__":
    main()
