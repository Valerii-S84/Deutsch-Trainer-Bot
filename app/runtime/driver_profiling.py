from __future__ import annotations

from time import perf_counter
from typing import Any

from app.runtime.timing import current_timing_query_label, record_timing_metric
from app.runtime.webhook_profiling import current_webhook_operation_label, record_webhook_metric

_sqlalchemy_asyncpg_profiling_installed = False
_redis_profiling_installed = False


def install_driver_profiling() -> None:
    install_sqlalchemy_asyncpg_profiling()
    install_redis_profiling()


def install_sqlalchemy_asyncpg_profiling() -> None:
    global _sqlalchemy_asyncpg_profiling_installed
    if _sqlalchemy_asyncpg_profiling_installed:
        return

    from sqlalchemy.dialects.postgresql.asyncpg import AsyncAdapt_asyncpg_connection

    original_prepare = AsyncAdapt_asyncpg_connection._prepare
    original_start_transaction = AsyncAdapt_asyncpg_connection._start_transaction

    async def timed_prepare(self, operation: str, invalidate_timestamp: float):
        label = current_timing_query_label()
        if label is None:
            return await original_prepare(self, operation, invalidate_timestamp)

        started = perf_counter()
        try:
            return await original_prepare(self, operation, invalidate_timestamp)
        finally:
            record_timing_metric(f"{label}.prepare_ms", (perf_counter() - started) * 1000)
            record_timing_metric(f"{label}.prepare_count", 1)

    async def timed_start_transaction(self):
        label = current_timing_query_label()
        if label is None:
            return await original_start_transaction(self)

        started = perf_counter()
        try:
            return await original_start_transaction(self)
        finally:
            record_timing_metric(f"{label}.tx_start_ms", (perf_counter() - started) * 1000)
            record_timing_metric(f"{label}.tx_start_count", 1)

    AsyncAdapt_asyncpg_connection._prepare = timed_prepare  # type: ignore[assignment]
    AsyncAdapt_asyncpg_connection._start_transaction = timed_start_transaction  # type: ignore[assignment]
    _sqlalchemy_asyncpg_profiling_installed = True


def install_redis_profiling() -> None:
    global _redis_profiling_installed
    if _redis_profiling_installed:
        return

    from redis.asyncio.client import Redis
    from redis.asyncio.connection import Connection, ConnectionPool

    original_execute_command = Redis.execute_command
    original_get_connection = ConnectionPool.get_connection
    original_connect = Connection._connect
    original_read_response = Connection.read_response

    async def timed_execute_command(self, *args: Any, **kwargs: Any):
        label = current_webhook_operation_label()
        if label is None:
            return await original_execute_command(self, *args, **kwargs)

        started = perf_counter()
        try:
            return await original_execute_command(self, *args, **kwargs)
        finally:
            record_webhook_metric(f"{label}.command_ms", (perf_counter() - started) * 1000)
            record_webhook_metric(f"{label}.command_count", 1)

    async def timed_get_connection(self, *args: Any, **kwargs: Any):
        label = current_webhook_operation_label()
        if label is None:
            return await original_get_connection(self, *args, **kwargs)

        before_total = _redis_pool_connection_count(self)
        started = perf_counter()
        try:
            return await original_get_connection(self, *args, **kwargs)
        finally:
            after_total = _redis_pool_connection_count(self)
            if after_total > before_total:
                record_webhook_metric(f"{label}.pool_new_connection_count", after_total - before_total)
            record_webhook_metric(f"{label}.pool_acquire_ms", (perf_counter() - started) * 1000)
            record_webhook_metric(f"{label}.pool_acquire_count", 1)

    async def timed_connect(self, *args: Any, **kwargs: Any):
        label = current_webhook_operation_label()
        if label is None:
            return await original_connect(self, *args, **kwargs)

        started = perf_counter()
        try:
            return await original_connect(self, *args, **kwargs)
        finally:
            record_webhook_metric(f"{label}.connect_ms", (perf_counter() - started) * 1000)
            record_webhook_metric(f"{label}.connect_count", 1)

    async def timed_read_response(self, *args: Any, **kwargs: Any):
        label = current_webhook_operation_label()
        if label is None:
            return await original_read_response(self, *args, **kwargs)

        started = perf_counter()
        try:
            return await original_read_response(self, *args, **kwargs)
        finally:
            record_webhook_metric(f"{label}.read_response_ms", (perf_counter() - started) * 1000)
            record_webhook_metric(f"{label}.read_response_count", 1)

    Redis.execute_command = timed_execute_command  # type: ignore[assignment]
    ConnectionPool.get_connection = timed_get_connection  # type: ignore[assignment]
    Connection._connect = timed_connect  # type: ignore[assignment]
    Connection.read_response = timed_read_response  # type: ignore[assignment]
    _redis_profiling_installed = True


def _redis_pool_connection_count(pool: Any) -> int:
    available = getattr(pool, "_available_connections", ())
    in_use = getattr(pool, "_in_use_connections", ())
    return len(available) + len(in_use)
