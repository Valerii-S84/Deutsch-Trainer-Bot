from __future__ import annotations

from redis.asyncio import Redis

from app.config import Settings

_shared_redis_client: Redis | None = None


def create_redis_client(settings: Settings) -> Redis:
    """Create the shared Redis client for one runtime process."""

    global _shared_redis_client

    redis_client = Redis.from_url(
        settings.redis_url,
        decode_responses=True,
        max_connections=settings.redis_max_connections,
    )
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


async def close_redis_client(redis_client: Redis | None) -> None:
    """Close the shared Redis client if it was created."""

    global _shared_redis_client

    if redis_client is not None:
        try:
            await redis_client.aclose()
        finally:
            if _shared_redis_client is redis_client:
                _shared_redis_client = None
