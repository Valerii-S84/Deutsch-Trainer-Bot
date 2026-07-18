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

    Redis.execute_command = _timed_redis_command(Redis.execute_command)  # type: ignore[assignment]
    ConnectionPool.get_connection = _timed_redis_pool_acquire(ConnectionPool.get_connection)  # type: ignore[assignment]
    Connection._connect = _timed_redis_connect(Connection._connect)  # type: ignore[assignment]
    Connection.read_response = _timed_redis_read_response(Connection.read_response)  # type: ignore[assignment]
    _redis_profiling_installed = True


def _timed_redis_command(original):
    async def timed_execute_command(self, *args: Any, **kwargs: Any):
        label = current_webhook_operation_label()
        if label is None:
            return await original(self, *args, **kwargs)

        started = perf_counter()
        try:
            return await original(self, *args, **kwargs)
        finally:
            record_webhook_metric(f"{label}.command_ms", (perf_counter() - started) * 1000)
            record_webhook_metric(f"{label}.command_count", 1)
    return timed_execute_command


def _timed_redis_pool_acquire(original):
    async def timed_get_connection(self, *args: Any, **kwargs: Any):
        label = current_webhook_operation_label()
        if label is None:
            return await original(self, *args, **kwargs)

        before_total = _redis_pool_connection_count(self)
        started = perf_counter()
        try:
            return await original(self, *args, **kwargs)
        finally:
            after_total = _redis_pool_connection_count(self)
            if after_total > before_total:
                record_webhook_metric(f"{label}.pool_new_connection_count", after_total - before_total)
            record_webhook_metric(f"{label}.pool_acquire_ms", (perf_counter() - started) * 1000)
            record_webhook_metric(f"{label}.pool_acquire_count", 1)
    return timed_get_connection


def _timed_redis_connect(original):
    async def timed_connect(self, *args: Any, **kwargs: Any):
        label = current_webhook_operation_label()
        if label is None:
            return await original(self, *args, **kwargs)

        started = perf_counter()
        try:
            return await original(self, *args, **kwargs)
        finally:
            record_webhook_metric(f"{label}.connect_ms", (perf_counter() - started) * 1000)
            record_webhook_metric(f"{label}.connect_count", 1)
    return timed_connect


def _timed_redis_read_response(original):
    async def timed_read_response(self, *args: Any, **kwargs: Any):
        label = current_webhook_operation_label()
        if label is None:
            return await original(self, *args, **kwargs)

        started = perf_counter()
        try:
            return await original(self, *args, **kwargs)
        finally:
            record_webhook_metric(f"{label}.read_response_ms", (perf_counter() - started) * 1000)
            record_webhook_metric(f"{label}.read_response_count", 1)
    return timed_read_response


def _redis_pool_connection_count(pool: Any) -> int:
    available = getattr(pool, "_available_connections", ())
    in_use = getattr(pool, "_in_use_connections", ())
    return len(available) + len(in_use)
