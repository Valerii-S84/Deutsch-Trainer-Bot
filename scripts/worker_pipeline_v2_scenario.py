from __future__ import annotations

import argparse
import asyncio
import contextlib
import contextvars
import json
import time
import traceback
from collections import Counter
from typing import Any

import asyncpg
from redis.asyncio import Redis
from sqlalchemy import event
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import scripts.worker_pipeline_v2_runtime as runtime_root
from scripts.worker_pipeline_v2_runtime import *
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


class RedisProbe:
    def __init__(self, client: Redis) -> None:
        self._client = client

    async def _record(self, method: str, operation: Any) -> object:
        metrics = CURRENT_REQUEST.get()
        started = time.perf_counter()
        try:
            return await operation
        finally:
            if metrics is not None:
                metrics.redis_calls[method] += 1
                metrics.redis_latency_ms[method] += (time.perf_counter() - started) * 1000

    async def set(self, *args: Any, **kwargs: Any) -> object:
        return await self._record("set", self._client.set(*args, **kwargs))

    async def time(self, *args: Any, **kwargs: Any) -> object:
        return await self._record("time", self._client.time(*args, **kwargs))

    async def eval(self, *args: Any, **kwargs: Any) -> object:
        return await self._record("eval", self._client.eval(*args, **kwargs))

    async def flushdb(self) -> object:
        return await self._client.flushdb()

    async def aclose(self) -> None:
        await self._client.aclose()


def _fast_payload_wrapper(original: Any):
    def wrapped(*args: Any, **kwargs: Any):
        metrics = CURRENT_REQUEST.get()
        started = time.perf_counter()
        payload = original(*args, **kwargs)
        if metrics is not None:
            metrics.payload_build_ms += (time.perf_counter() - started) * 1000
            if not metrics.payload_size_bytes:
                metrics.payload_size_bytes = len(json.dumps(payload, default=runtime_root._json_default).encode("utf-8"))
        return payload
    return wrapped


def _fallback_payload_wrapper(original: Any):
    def wrapped(processor: Any, *args: Any, **kwargs: Any):
        metrics = CURRENT_REQUEST.get()
        started = time.perf_counter()
        payload = original(processor, *args, **kwargs)
        if metrics is not None:
            metrics.payload_build_ms += (time.perf_counter() - started) * 1000
            if not metrics.payload_size_bytes:
                metrics.payload_size_bytes = len(json.dumps(payload, default=runtime_root._json_default).encode("utf-8"))
        return payload
    return wrapped


def _enqueue_wrapper(original: Any):
    async def wrapped(
        repository: Any, db: Any, *, event_type: Any, aggregate_type: Any,
        aggregate_id: Any, idempotency_key: Any, payload: Any,
    ):
        metrics = CURRENT_REQUEST.get()
        if metrics is not None:
            started_serialize = time.perf_counter()
            payload_json = json.dumps(payload, default=runtime_root._json_default)
            metrics.json_serialize_ms += (time.perf_counter() - started_serialize) * 1000
            metrics.payload_size_bytes = max(metrics.payload_size_bytes, len(payload_json.encode("utf-8")))
        started = time.perf_counter()
        result = await original(
            repository, db, event_type=event_type, aggregate_type=aggregate_type,
            aggregate_id=aggregate_id, idempotency_key=idempotency_key, payload=payload,
        )
        if metrics is not None:
            metrics.outbox_insert_ms += (time.perf_counter() - started) * 1000
        return result
    return wrapped


class ScenarioDatabaseMixin:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.settings = __import__("app.config", fromlist=["get_settings"]).get_settings()
        self.arrival_profile = build_arrival_profile(args)
        self.session_selection_profile = build_session_selection_profile(args)
        self.max_in_flight_limit = resolve_max_in_flight(args, self.settings)
        self.in_flight_gate = (
            asyncio.Semaphore(self.max_in_flight_limit) if self.max_in_flight_limit is not None else None
        )
        self.cpu_sampler = CpuStackSampler(interval_ms=args.cpu_profile_interval_ms) if args.cpu_profile_output else None
        self.cpu_profile_holder: dict[str, object] = {}
        self.runtime_stats = RuntimeStats()
        self.app_requests: dict[int, RequestMetrics] = {}
        self.connection_requests: dict[int, int] = {}
        self.redis_client: RedisProbe | None = None
        self.worker_task: asyncio.Task[None] | None = None
        self.sampler_task: asyncio.Task[None] | None = None
        self.inspector_conn: asyncpg.Connection | None = None
        self.stop_event = asyncio.Event()
        self.duplicate_guard: RedisDuplicateUpdateGuard | None = None
        self.rate_limiter: RedisRateLimiter | None = None
        self.run_update_base = time.time_ns()
        self.run_meta: dict[str, Any] = {}
        self.single_probe: dict[str, Any] = {}
        self.drain_seconds = 0.0
        self.original_fast_payload = fast_path_module._answer_accepted_payload
        self.original_fallback_payload = TrainingAnswerProcessor._answer_accepted_payload
        self.original_enqueue = OutboxRepository.enqueue
        self.db_session_module = db_session_module

    @contextlib.asynccontextmanager
    async def app_session_scope(self):
        self.runtime_stats.open_sessions += 1
        self.runtime_stats.max_open_sessions = max(
            self.runtime_stats.max_open_sessions, self.runtime_stats.open_sessions,
        )
        try:
            async with AsyncSessionLocal() as db:
                yield db
        finally:
            self.runtime_stats.open_sessions = max(0, self.runtime_stats.open_sessions - 1)

    async def outbox_counts(self) -> dict[str, int]:
        assert self.inspector_conn is not None
        rows = await self.inspector_conn.fetch(
            "SELECT status, COUNT(*)::int AS count FROM outbox_events GROUP BY status"
        )
        counts = {
            OUTBOX_PENDING: 0, OUTBOX_PROCESSING: 0, OUTBOX_DONE: 0,
            OUTBOX_FAILED: 0, OUTBOX_DEAD: 0,
        }
        for status, count in rows:
            counts[str(status)] = int(count)
        return counts

    async def pending_lag_seconds(self) -> float:
        assert self.inspector_conn is not None
        value = await self.inspector_conn.fetchval(
            "SELECT COALESCE(EXTRACT(EPOCH FROM (NOW() - MIN(created_at))), 0) "
            "FROM outbox_events WHERE status = 'pending'"
        )
        return round(float(value or 0.0), 3)

    async def duplicate_group_count(self) -> int:
        assert self.inspector_conn is not None
        value = await self.inspector_conn.fetchval(
            "SELECT COUNT(*)::int FROM (SELECT user_id, session_id, external_quiz_id "
            "FROM user_answers GROUP BY user_id, session_id, external_quiz_id HAVING COUNT(*) > 1) groups"
        )
        return int(value or 0)

    async def pg_activity_snapshot(self) -> dict[str, int]:
        assert self.inspector_conn is not None
        row = await self.inspector_conn.fetchrow(
            "SELECT COUNT(*)::int AS total, "
            "COUNT(*) FILTER (WHERE state = 'active')::int AS active, "
            "COUNT(*) FILTER (WHERE state = 'active' AND wait_event_type IS NOT NULL)::int AS waiting "
            "FROM pg_stat_activity WHERE datname = current_database() AND application_name <> $1",
            APP_NAME,
        )
        return {"total": int(row["total"]), "active": int(row["active"]), "waiting": int(row["waiting"])}

    async def pg_wait_events_snapshot(self) -> list[dict[str, object]]:
        assert self.inspector_conn is not None
        rows = await self.inspector_conn.fetch(
            "SELECT wait_event_type, wait_event, COUNT(*)::int AS count FROM pg_stat_activity "
            "WHERE datname = current_database() AND application_name <> $1 AND wait_event_type IS NOT NULL "
            "GROUP BY wait_event_type, wait_event ORDER BY count DESC, wait_event_type, wait_event LIMIT 10",
            APP_NAME,
        )
        return [
            {"wait_event_type": row["wait_event_type"], "wait_event": row["wait_event"], "count": int(row["count"])}
            for row in rows
        ]

    async def outbox_schema(self) -> dict[str, object]:
        assert self.inspector_conn is not None
        indexes = await self.inspector_conn.fetch(
            "SELECT indexname, indexdef FROM pg_indexes WHERE tablename = 'outbox_events' ORDER BY indexname"
        )
        triggers = await self.inspector_conn.fetch(
            "SELECT tgname FROM pg_trigger JOIN pg_class ON pg_trigger.tgrelid = pg_class.oid "
            "WHERE pg_class.relname = 'outbox_events' AND NOT pg_trigger.tgisinternal ORDER BY tgname"
        )
        constraints = await self.inspector_conn.fetch(
            "SELECT conname, contype FROM pg_constraint JOIN pg_class ON pg_constraint.conrelid = pg_class.oid "
            "WHERE pg_class.relname = 'outbox_events' ORDER BY conname"
        )
        return {
            "indexes": [dict(row) for row in indexes], "triggers": [dict(row) for row in triggers],
            "constraints": [dict(row) for row in constraints],
        }

    async def sampler(self) -> None:
        started_wall = time.perf_counter()
        started_cpu = time.process_time()
        while not self.stop_event.is_set():
            await self._sample_runtime(started_wall, started_cpu)
            await asyncio.sleep(0.1)

    async def _sample_runtime(self, started_wall: float, started_cpu: float) -> None:
        stats = self.runtime_stats
        snapshot = await self.pg_activity_snapshot()
        stats.max_pg_total_connections = max(stats.max_pg_total_connections, snapshot["total"])
        stats.max_pg_active_connections = max(stats.max_pg_active_connections, snapshot["active"])
        if snapshot["waiting"] >= stats.max_pg_waiting_connections:
            stats.max_pg_waiting_connections = snapshot["waiting"]
            stats.pg_wait_events_at_max_waiting = await self.pg_wait_events_snapshot()
        counts = await self.outbox_counts()
        stats.max_pending = max(stats.max_pending, counts[OUTBOX_PENDING])
        stats.max_processing = max(stats.max_processing, counts[OUTBOX_PROCESSING])
        stats.max_worker_lag_seconds = max(stats.max_worker_lag_seconds, await self.pending_lag_seconds())
        stats.app_pool_status_samples.append(sample_pool_state("app", db_session_module._engine.sync_engine.pool))
        stats.worker_pool_status_samples.append(sample_pool_state("worker", db_session_module._worker_engine.sync_engine.pool))
        elapsed_wall = max(time.perf_counter() - started_wall, 0.001)
        stats.max_cpu_percent = max(stats.max_cpu_percent, (time.process_time() - started_cpu) / elapsed_wall * 100)
        stats.max_rss_mb = max(stats.max_rss_mb, current_max_rss_mb())

class ScenarioInstrumentationMixin(ScenarioDatabaseMixin):
    def install_instrumentation(self) -> None:
        event.listen(db_session_module._engine.sync_engine, "before_cursor_execute", self._before_cursor_execute)
        event.listen(db_session_module._engine.sync_engine.pool, "checkout", self._checkout)
        event.listen(db_session_module._engine.sync_engine.pool, "checkin", self._checkin)
        fast_path_module._answer_accepted_payload = _fast_payload_wrapper(self.original_fast_payload)
        TrainingAnswerProcessor._answer_accepted_payload = _fallback_payload_wrapper(self.original_fallback_payload)
        OutboxRepository.enqueue = _enqueue_wrapper(self.original_enqueue)

    def _before_cursor_execute(
        self, conn: Any, cursor: Any, statement: str, parameters: Any, context: Any, executemany: Any,
    ) -> None:
        metrics = CURRENT_REQUEST.get()
        if metrics is not None:
            metrics.sql_count += 1
            if len(metrics.sql_statements) < 10:
                metrics.sql_statements.append(statement.strip())

    def _checkout(self, dbapi_connection: Any, connection_record: Any, connection_proxy: Any) -> None:
        stats = self.runtime_stats
        stats.total_checkouts += 1
        stats.current_checked_out += 1
        stats.max_checked_out = max(stats.max_checked_out, stats.current_checked_out)
        metrics = CURRENT_REQUEST.get()
        if metrics is not None:
            metrics.connection_checkouts += 1
            self.connection_requests[id(connection_record)] = metrics.request_id
        connection_record.info["dtb_checkout_started"] = time.perf_counter()

    def _checkin(self, dbapi_connection: Any, connection_record: Any) -> None:
        self.runtime_stats.current_checked_out = max(0, self.runtime_stats.current_checked_out - 1)
        started = connection_record.info.pop("dtb_checkout_started", None)
        request_id = self.connection_requests.pop(id(connection_record), None)
        if started is None or request_id is None:
            return
        metrics = self.app_requests.get(request_id)
        if metrics is not None:
            metrics.connection_hold_ms += (time.perf_counter() - started) * 1000

    def request_token(self, request_id: int) -> contextvars.Token[RequestMetrics | None]:
        return CURRENT_REQUEST.set(self.app_requests[request_id])

    def _request_metrics(self, request_id: int) -> RequestMetrics:
        session_id = measurement_session_id(
            self.args.session_offset, request_id,
            session_selection_profile=self.session_selection_profile,
        )
        return RequestMetrics(
            request_id=request_id, session_id=session_id,
            telegram_user_id=7_000_000_000 + session_id,
            update_id=measurement_update_id(self.run_update_base, request_id),
        )

    async def single_request_probe(self, service: TrainingSessionService) -> dict[str, object]:
        session_id = self.args.seeded_session_count
        metrics = RequestMetrics(
            request_id=100_000, session_id=session_id,
            telegram_user_id=7_000_000_000 + session_id,
            update_id=measurement_update_id(self.run_update_base, 9_900_000 + session_id),
        )
        self.app_requests[metrics.request_id] = metrics
        token = self.request_token(metrics.request_id)
        try:
            await self._submit_answer(service, metrics, commit=False)
        finally:
            CURRENT_REQUEST.reset(token)
        return {
            "accepted": metrics.accepted, "duplicate": metrics.duplicate,
            "sql_count": metrics.sql_count, "sql_statements": metrics.sql_statements,
            "db_acquire_wait_ms": round(metrics.db_acquire_wait_ms, 3),
            "connection_checkouts": metrics.connection_checkouts,
            "connection_hold_ms": round(metrics.connection_hold_ms, 3),
            "payload_build_ms": round(metrics.payload_build_ms, 3),
            "json_serialize_ms": round(metrics.json_serialize_ms, 3),
            "payload_size_bytes": metrics.payload_size_bytes,
            "outbox_insert_ms": round(metrics.outbox_insert_ms, 3),
            "timing_spans_ms": {key: round(value, 3) for key, value in metrics.timing_spans_ms.items()},
        }

    async def _authorize_request(self, metrics: RequestMetrics) -> bool:
        assert self.duplicate_guard is not None and self.rate_limiter is not None
        if not await self.duplicate_guard.accept(metrics.update_id):
            metrics.duplicate = True
            return False
        decision = await self.rate_limiter.check(
            action=ACTION_ANSWER, identity=f"user:{metrics.telegram_user_id}",
        )
        if decision.allowed:
            return True
        metrics.error_type = "RateLimited"
        metrics.error_message = f"retry_after={decision.retry_after_seconds}"
        return False

    async def _submit_answer(
        self, service: TrainingSessionService, metrics: RequestMetrics, *, commit: bool,
    ) -> None:
        async with self.app_session_scope() as db:
            metrics.session_opens += 1
            timing, timing_token = begin_timing()
            connection_started = time.perf_counter()
            await db.connection()
            metrics.db_acquire_wait_ms = (time.perf_counter() - connection_started) * 1000
            try:
                result = await service.submit_answer(
                    db, metrics.telegram_user_id, session_id=metrics.session_id,
                    question_token=f"tok{metrics.session_id:08d}",
                    selected_option_id=SELECTED_ANSWER, telegram_update_id=metrics.update_id,
                )
                if commit:
                    await db.commit()
            finally:
                end_timing(timing_token)
            metrics.timing_spans_ms = timing
            if not commit:
                await db.rollback()
            metrics.accepted = not result.is_duplicate
            metrics.duplicate = result.is_duplicate

    async def invoke_request(self, service: TrainingSessionService, request_id: int) -> None:
        metrics = self._request_metrics(request_id)
        self.app_requests[request_id] = metrics
        token = self.request_token(request_id)
        started = time.perf_counter()
        gate_acquired = False
        try:
            if self.in_flight_gate is not None:
                queue_started = time.perf_counter()
                await self.in_flight_gate.acquire()
                gate_acquired = True
                metrics.queue_wait_ms = (time.perf_counter() - queue_started) * 1000
            self.runtime_stats.current_in_flight_requests += 1
            self.runtime_stats.max_in_flight_requests = max(
                self.runtime_stats.max_in_flight_requests,
                self.runtime_stats.current_in_flight_requests,
            )
            if await self._authorize_request(metrics):
                await self._submit_answer(service, metrics, commit=True)
        except Exception as exc:
            metrics.error_type = exc.__class__.__name__
            metrics.error_message = str(exc)
            metrics.error_traceback = "".join(traceback.format_exception(exc))
        finally:
            metrics.total_ms = (time.perf_counter() - started) * 1000
            self.runtime_stats.current_in_flight_requests = max(
                0, self.runtime_stats.current_in_flight_requests - 1,
            )
            if gate_acquired:
                self.in_flight_gate.release()
            CURRENT_REQUEST.reset(token)

    async def load_run(self, service: TrainingSessionService) -> dict[str, object]:
        started = time.perf_counter()
        tasks: list[asyncio.Task[None]] = []
        dispatch_gap_ms: list[float] = []
        dispatch_lag_ms: list[float] = []
        last_dispatch: float | None = None
        if self.cpu_sampler is not None:
            self.cpu_sampler.start()
        try:
            for request_id in range(self.args.total_requests):
                target = started + self.arrival_profile.target_offset_seconds(request_id)
                if target > time.perf_counter():
                    await asyncio.sleep(target - time.perf_counter())
                dispatched = time.perf_counter()
                dispatch_lag_ms.append(max(0.0, (dispatched - target) * 1000))
                if last_dispatch is not None:
                    dispatch_gap_ms.append((dispatched - last_dispatch) * 1000)
                last_dispatch = dispatched
                tasks.append(asyncio.create_task(self.invoke_request(service, request_id)))
            await asyncio.gather(*tasks)
            elapsed = time.perf_counter() - started
            return {
                "request_duration_sec": round(elapsed, 3),
                "achieved_rps": round(self.args.total_requests / max(elapsed, 0.001), 3),
                "scheduled_dispatch_span_sec": self.arrival_profile.metadata(
                    self.args.total_requests
                )["scheduled_dispatch_span_sec"],
                "dispatch_gap_ms": summarize_numeric(dispatch_gap_ms),
                "dispatch_lag_ms": summarize_numeric(dispatch_lag_ms),
                "max_in_flight_requests": self.runtime_stats.max_in_flight_requests,
            }
        finally:
            if self.cpu_sampler is not None:
                self.cpu_profile_holder["summary"] = self.cpu_sampler.stop()

class ScenarioRunner(ScenarioInstrumentationMixin):
    async def open_resources(self) -> TrainingSessionService:
        inspector_url = make_url(database_url()).set(query={"application_name": APP_NAME})
        inspector_dsn = inspector_url.render_as_string(hide_password=False).replace("+asyncpg", "")
        self.inspector_conn = await asyncpg.connect(inspector_dsn)
        self.redis_client = RedisProbe(create_redis_client(self.settings))
        await self.redis_client.flushdb()
        self.duplicate_guard = RedisDuplicateUpdateGuard(
            self.redis_client, ttl_seconds=self.settings.telegram_duplicate_update_ttl_seconds,
        )
        self.rate_limiter = RedisRateLimiter(self.redis_client)
        return TrainingSessionService()

    async def capture_before(self, service: TrainingSessionService) -> None:
        self.before_counts = await self.outbox_counts()
        self.before_pg = await self.pg_activity_snapshot()
        self.before_pool = sample_pool_state("app", db_session_module._engine.sync_engine.pool)
        self.single_probe = await self.single_request_probe(service)

    async def start_worker(self) -> None:
        if not self.args.workers_on:
            return
        worker = OutboxWorker(session_factory=async_sessionmaker(
            db_session_module._worker_engine, expire_on_commit=False, class_=AsyncSession,
        ))
        self.worker_task = asyncio.create_task(worker.run_forever(idle_sleep_seconds=0.05))

    async def drain_outbox(self) -> None:
        started = time.perf_counter()
        if self.args.workers_on:
            while time.perf_counter() - started <= 30:
                counts = await self.outbox_counts()
                if counts[OUTBOX_PENDING] == 0 and counts[OUTBOX_PROCESSING] == 0:
                    break
                await asyncio.sleep(0.1)
        self.drain_seconds = round(time.perf_counter() - started, 3) if self.args.workers_on else 0.0

    async def stop_worker(self) -> None:
        if self.worker_task is None:
            return
        self.worker_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self.worker_task
        self.worker_task = None

    async def capture_after(self) -> None:
        assert self.redis_client is not None
        self.after_counts = await self.outbox_counts()
        self.after_pg_pre_dispose = await self.pg_activity_snapshot()
        self.duplicate_groups = await self.duplicate_group_count()
        await dispose_engine()
        self.after_pg_post_dispose = await self.pg_activity_snapshot()
        await self.redis_client.aclose()
        self.redis_client = None

    async def run(self) -> None:
        self.install_instrumentation()
        try:
            service = await self.open_resources()
            await self.capture_before(service)
            await self.start_worker()
            self.sampler_task = asyncio.create_task(self.sampler())
            self.run_meta = await self.load_run(service)
            self.stop_event.set()
            await asyncio.wait_for(self.sampler_task, timeout=5)
            self.sampler_task = None
            await self.drain_outbox()
            await self.stop_worker()
            await self.capture_after()
            from scripts.worker_pipeline_v2_result import build_scenario_result
            result = await build_scenario_result(self)
            print(json.dumps(result, indent=2, default=runtime_root._json_default))
        finally:
            await self.cleanup()

    async def cleanup(self) -> None:
        fast_path_module._answer_accepted_payload = self.original_fast_payload
        TrainingAnswerProcessor._answer_accepted_payload = self.original_fallback_payload
        OutboxRepository.enqueue = self.original_enqueue
        self.stop_event.set()
        for task in (self.worker_task, self.sampler_task):
            if task is not None:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
        if self.redis_client is not None:
            with contextlib.suppress(Exception):
                await self.redis_client.aclose()
        if self.inspector_conn is not None:
            await self.inspector_conn.close()
