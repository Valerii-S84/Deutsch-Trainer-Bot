from __future__ import annotations

import asyncio

from redis.asyncio import BlockingConnectionPool, Redis

from app.config import Settings

_shared_redis_client: Redis | None = None


def create_redis_client(settings: Settings) -> Redis:
    """Create the shared Redis client for one runtime process."""

    global _shared_redis_client

    if _shared_redis_client is not None:
        return _shared_redis_client

    pool = BlockingConnectionPool.from_url(
        settings.redis_url,
        decode_responses=True,
        max_connections=settings.redis_max_connections,
        timeout=settings.redis_pool_timeout_seconds,
    )
    redis_client = Redis(connection_pool=pool)
    _shared_redis_client = redis_client
    return redis_client


def get_shared_redis_client() -> Redis | None:
    """Return the process-shared Redis client when runtime has created one."""

    return _shared_redis_client


def get_or_create_shared_redis_client(settings: Settings) -> Redis:
    """Reuse the process-shared Redis client or create it lazily."""

    shared = get_shared_redis_client()
    if shared is not None:
        return shared
    return create_redis_client(settings)


async def warm_redis_client(redis_client: Redis | None, *, connection_count: int) -> dict[str, int]:
    """Open Redis pool connections before the hot request path sees traffic."""

    if redis_client is None or connection_count <= 0:
        return {"requested": 0, "succeeded": 0, "failed": 0}

    results = await asyncio.gather(
        *(redis_client.ping() for _ in range(connection_count)),
        return_exceptions=True,
    )
    failed = sum(isinstance(item, Exception) for item in results)
    return {
        "requested": connection_count,
        "succeeded": connection_count - failed,
        "failed": failed,
    }


async def close_redis_client(redis_client: Redis | None) -> None:
    """Close the shared Redis client if it was created."""

    global _shared_redis_client

    client = redis_client or _shared_redis_client
    if client is not None:
        try:
            await client.aclose()
        finally:
            if _shared_redis_client is client:
                _shared_redis_client = None
