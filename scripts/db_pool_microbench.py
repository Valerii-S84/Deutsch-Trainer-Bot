from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import os
import resource
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import asyncpg
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncConnection, create_async_engine


APP_NAME = "dtb_db_pool_microbench"
INSPECTOR_APP_NAME = "dtb_db_pool_microbench_inspector"
TABLE_NAME = "db_pool_microbench"
DEFAULT_REQUESTS = 500
DEFAULT_CONCURRENCY = (10, 25, 50, 100)
DEFAULT_OPERATIONS = (
    "acquire_only",
    "select1",
    "select1_tx",
    "insert_simple",
    "insert_on_conflict",
)
DEFAULT_POOL_CONFIGS = ("5:5", "10:10", "20:20", "40:20")
DEFAULT_POOL_TIMEOUTS = (2.0, 5.0, 10.0)


@dataclass
class RequestResult:
    acquire_wait_ms: float
    query_ms: float
    transaction_hold_ms: float
    error_type: str | None = None


def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * p)))
    return round(ordered[index], 3)


def stats(values: list[float]) -> dict[str, float]:
    return {
        "p50": percentile(values, 0.50),
        "p95": percentile(values, 0.95),
        "p99": percentile(values, 0.99),
        "max": round(max(values, default=0.0), 3),
    }


def database_url() -> str:
    value = os.environ.get("DATABASE_URL")
    if not value:
        raise SystemExit("DATABASE_URL is required")
    return value


def parse_int_list(raw: str | None, default: tuple[int, ...]) -> list[int]:
    if not raw:
        return list(default)
    return [int(item.strip()) for item in raw.split(",") if item.strip()]


def parse_float_list(raw: str | None, default: tuple[float, ...]) -> list[float]:
    if not raw:
        return list(default)
    return [float(item.strip()) for item in raw.split(",") if item.strip()]


def parse_str_list(raw: str | None, default: tuple[str, ...]) -> list[str]:
    if not raw:
        return list(default)
    return [item.strip() for item in raw.split(",") if item.strip()]


def redact_dsn(dsn: str) -> str:
    if "@" not in dsn:
        return dsn
    prefix, suffix = dsn.rsplit("@", 1)
    if ":" not in prefix:
        return dsn
    scheme, _rest = prefix.split("://", 1)
    user = _rest.split(":", 1)[0]
    return f"{scheme}://{user}:***@{suffix}"


class PoolTracker:
    def __init__(self) -> None:
        self.max_checked_out = 0
        self.current_checked_out = 0
        self.max_overflow = 0

    def bind(self, engine: AsyncEngine) -> None:
        pool = engine.sync_engine.pool

        @event.listens_for(pool, "checkout")
        def _checkout(dbapi_connection, connection_record, connection_proxy) -> None:
            self.current_checked_out += 1
            self.max_checked_out = max(self.max_checked_out, self.current_checked_out)
            self.max_overflow = max(self.max_overflow, int(pool.overflow()))

        @event.listens_for(pool, "checkin")
        def _checkin(dbapi_connection, connection_record) -> None:
            self.current_checked_out = max(0, self.current_checked_out - 1)


class Sampler:
    def __init__(self, inspector: asyncpg.Connection, pool) -> None:
        self._inspector = inspector
        self._pool = pool
        self.max_pg_total = 0
        self.max_pg_active = 0
        self.max_pg_waiting = 0
        self.max_cpu_percent = 0.0
        self.max_rss_mb = 0.0
        self._stop = asyncio.Event()

    async def run(self) -> None:
        started_wall = time.perf_counter()
        started_cpu = time.process_time()
        try:
            while not self._stop.is_set():
                row = await self._inspector.fetchrow(
                    """
                    SELECT
                        COUNT(*)::int AS total,
                        COUNT(*) FILTER (WHERE state = 'active')::int AS active,
                        COUNT(*) FILTER (WHERE state = 'active' AND wait_event_type IS NOT NULL)::int AS waiting
                    FROM pg_stat_activity
                    WHERE datname = current_database()
                      AND application_name <> $1
                    """,
                    INSPECTOR_APP_NAME,
                )
                self.max_pg_total = max(self.max_pg_total, int(row["total"]))
                self.max_pg_active = max(self.max_pg_active, int(row["active"]))
                self.max_pg_waiting = max(self.max_pg_waiting, int(row["waiting"]))
                elapsed_wall = max(time.perf_counter() - started_wall, 0.001)
                elapsed_cpu = max(time.process_time() - started_cpu, 0.0)
                self.max_cpu_percent = max(self.max_cpu_percent, (elapsed_cpu / elapsed_wall) * 100.0)
                self.max_rss_mb = max(
                    self.max_rss_mb,
                    float(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss) / 1024.0,
                )
                await asyncio.sleep(0.05)
        except asyncio.CancelledError:
            raise

    def stop(self) -> None:
        self._stop.set()


async def ensure_table(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        await conn.execute(
            text(
                f"""
                CREATE TABLE IF NOT EXISTS {TABLE_NAME} (
                    id BIGSERIAL PRIMARY KEY,
                    bench_key TEXT NOT NULL UNIQUE,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
        )


async def prepare_operation(engine: AsyncEngine, operation: str, run_id: str) -> None:
    async with engine.begin() as conn:
        if operation == "insert_on_conflict":
            await conn.execute(
                text(
                    f"""
                    INSERT INTO {TABLE_NAME} (bench_key)
                    VALUES (:bench_key)
                    ON CONFLICT (bench_key) DO NOTHING
                    """
                ),
                {"bench_key": f"{run_id}:conflict"},
            )


async def warm_pool(engine: AsyncEngine, *, connections: int) -> None:
    count = max(1, connections)

    async def one_connection() -> None:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))

    await asyncio.gather(*(one_connection() for _ in range(count)))


async def cleanup_run(engine: AsyncEngine, run_id: str) -> None:
    async with engine.begin() as conn:
        await conn.execute(
            text(f"DELETE FROM {TABLE_NAME} WHERE bench_key LIKE :prefix"),
            {"prefix": f"{run_id}%"},
        )


async def execute_operation(
    engine: AsyncEngine,
    operation: str,
    run_id: str,
    request_id: int,
) -> RequestResult:
    acquire_started = time.perf_counter()
    query_ms = 0.0

    if operation == "acquire_only":
        async with engine.connect() as conn:
            acquired_at = time.perf_counter()
            acquire_wait_ms = (acquired_at - acquire_started) * 1000
            return RequestResult(
                acquire_wait_ms=acquire_wait_ms,
                query_ms=0.0,
                transaction_hold_ms=(time.perf_counter() - acquired_at) * 1000,
            )

    if operation == "select1":
        async with engine.connect() as conn:
            acquired_at = time.perf_counter()
            query_started = time.perf_counter()
            await conn.execute(text("SELECT 1"))
            query_ms = (time.perf_counter() - query_started) * 1000
            return RequestResult(
                acquire_wait_ms=(acquired_at - acquire_started) * 1000,
                query_ms=query_ms,
                transaction_hold_ms=(time.perf_counter() - acquired_at) * 1000,
            )

    if operation == "select1_tx":
        async with engine.begin() as conn:
            acquired_at = time.perf_counter()
            query_started = time.perf_counter()
            await conn.execute(text("SELECT 1"))
            query_ms = (time.perf_counter() - query_started) * 1000
            return RequestResult(
                acquire_wait_ms=(acquired_at - acquire_started) * 1000,
                query_ms=query_ms,
                transaction_hold_ms=(time.perf_counter() - acquired_at) * 1000,
            )

    if operation == "insert_simple":
        async with engine.begin() as conn:
            acquired_at = time.perf_counter()
            query_started = time.perf_counter()
            await conn.execute(
                text(f"INSERT INTO {TABLE_NAME} (bench_key) VALUES (:bench_key)"),
                {"bench_key": f"{run_id}:insert:{request_id}"},
            )
            query_ms = (time.perf_counter() - query_started) * 1000
            return RequestResult(
                acquire_wait_ms=(acquired_at - acquire_started) * 1000,
                query_ms=query_ms,
                transaction_hold_ms=(time.perf_counter() - acquired_at) * 1000,
            )

    if operation == "insert_on_conflict":
        async with engine.begin() as conn:
            acquired_at = time.perf_counter()
            query_started = time.perf_counter()
            await conn.execute(
                text(
                    f"""
                    INSERT INTO {TABLE_NAME} (bench_key)
                    VALUES (:bench_key)
                    ON CONFLICT (bench_key) DO NOTHING
                    """
                ),
                {"bench_key": f"{run_id}:conflict"},
            )
            query_ms = (time.perf_counter() - query_started) * 1000
            return RequestResult(
                acquire_wait_ms=(acquired_at - acquire_started) * 1000,
                query_ms=query_ms,
                transaction_hold_ms=(time.perf_counter() - acquired_at) * 1000,
            )

    raise ValueError(f"Unsupported operation: {operation}")


async def run_case(
    *,
    dsn: str,
    pool_size: int,
    max_overflow: int,
    pool_timeout: float,
    pre_ping: bool,
    operation: str,
    concurrency: int,
    requests: int,
) -> dict[str, Any]:
    tracker = PoolTracker()
    engine = create_async_engine(
        dsn,
        future=True,
        pool_size=pool_size,
        max_overflow=max_overflow,
        pool_timeout=pool_timeout,
        pool_pre_ping=pre_ping,
        connect_args={"server_settings": {"application_name": APP_NAME}},
    )
    tracker.bind(engine)
    await ensure_table(engine)

    inspector = await asyncpg.connect(
        dsn.replace("+asyncpg", ""),
        server_settings={"application_name": INSPECTOR_APP_NAME},
    )
    run_id = uuid4().hex
    await prepare_operation(engine, operation, run_id)
    await warm_pool(engine, connections=min(pool_size, concurrency))

    sampler = Sampler(inspector, engine.sync_engine.pool)
    sampler_task = asyncio.create_task(sampler.run())
    semaphore = asyncio.Semaphore(concurrency)
    results: list[RequestResult] = []
    started = time.perf_counter()

    async def one_request(request_id: int) -> None:
        async with semaphore:
            try:
                result = await execute_operation(engine, operation, run_id, request_id)
            except Exception as exc:
                result = RequestResult(
                    acquire_wait_ms=0.0,
                    query_ms=0.0,
                    transaction_hold_ms=0.0,
                    error_type=exc.__class__.__name__,
                )
            results.append(result)

    try:
        await asyncio.gather(*(one_request(request_id) for request_id in range(requests)))
    finally:
        sampler.stop()
        with contextlib.suppress(asyncio.CancelledError):
            await sampler_task
        await cleanup_run(engine, run_id)
        await engine.dispose()
        await inspector.close()

    elapsed = max(time.perf_counter() - started, 0.001)
    acquire_waits = [result.acquire_wait_ms for result in results if result.error_type is None]
    query_times = [result.query_ms for result in results if result.error_type is None]
    hold_times = [result.transaction_hold_ms for result in results if result.error_type is None]
    errors = [result.error_type for result in results if result.error_type is not None]

    return {
        "operation": operation,
        "concurrency": concurrency,
        "requests": requests,
        "pool_size": pool_size,
        "max_overflow": max_overflow,
        "pool_timeout": pool_timeout,
        "pool_pre_ping": pre_ping,
        "accepted": len(results) - len(errors),
        "errors": len(errors),
        "error_types": {
            error_type: errors.count(error_type)
            for error_type in sorted(set(errors))
            if error_type is not None
        },
        "throughput_per_sec": round(requests / elapsed, 2),
        "acquire_wait_ms": stats(acquire_waits),
        "query_time_ms": stats(query_times),
        "transaction_hold_ms": stats(hold_times),
        "pool_checked_out_max": tracker.max_checked_out,
        "pool_overflow_max": tracker.max_overflow,
        "pg_stat_activity_max": {
            "total": sampler.max_pg_total,
            "active": sampler.max_pg_active,
            "waiting": sampler.max_pg_waiting,
        },
        "cpu_ram_approx": {
            "cpu_percent": round(sampler.max_cpu_percent, 3),
            "max_rss_mb": round(sampler.max_rss_mb, 3),
        },
    }


async def run_matrix(args: argparse.Namespace) -> None:
    dsn = database_url()
    operations = parse_str_list(args.operations, DEFAULT_OPERATIONS)
    concurrencies = parse_int_list(args.concurrency, DEFAULT_CONCURRENCY)
    pool_timeouts = parse_float_list(args.pool_timeouts, DEFAULT_POOL_TIMEOUTS)
    pool_configs = parse_str_list(args.pool_configs, DEFAULT_POOL_CONFIGS)

    results: list[dict[str, Any]] = []
    for config in pool_configs:
        pool_size_raw, overflow_raw = config.split(":", 1)
        pool_size = int(pool_size_raw)
        max_overflow = int(overflow_raw)
        for pool_timeout in pool_timeouts:
            for operation in operations:
                for concurrency in concurrencies:
                    results.append(
                        await run_case(
                            dsn=dsn,
                            pool_size=pool_size,
                            max_overflow=max_overflow,
                            pool_timeout=pool_timeout,
                            pre_ping=args.pool_pre_ping,
                            operation=operation,
                            concurrency=concurrency,
                            requests=args.requests,
                        )
                    )

    print(
        json.dumps(
            {
                "generated_at": datetime.now(UTC).isoformat(),
                "database_url_redacted": redact_dsn(dsn),
                "requests_per_case": args.requests,
                "operations": operations,
                "concurrency_values": concurrencies,
                "pool_configs": pool_configs,
                "pool_timeouts": pool_timeouts,
                "pool_pre_ping": args.pool_pre_ping,
                "results": results,
            },
            indent=2,
        )
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="DB pool microbenchmark matrix.")
    parser.add_argument("--requests", type=int, default=DEFAULT_REQUESTS)
    parser.add_argument("--operations", default=",".join(DEFAULT_OPERATIONS))
    parser.add_argument("--concurrency", default=",".join(str(value) for value in DEFAULT_CONCURRENCY))
    parser.add_argument("--pool-configs", default=",".join(DEFAULT_POOL_CONFIGS))
    parser.add_argument("--pool-timeouts", default=",".join(str(value) for value in DEFAULT_POOL_TIMEOUTS))
    parser.add_argument("--pool-pre-ping", action=argparse.BooleanOptionalAction, default=True)
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    asyncio.run(run_matrix(args))


if __name__ == "__main__":
    main()
