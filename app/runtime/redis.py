from __future__ import annotations

from redis.asyncio import Redis

from app.config import Settings


def create_redis_client(settings: Settings) -> Redis:
    """Create the shared Redis client for one runtime process."""

    return Redis.from_url(
        settings.redis_url,
        decode_responses=True,
        max_connections=settings.redis_max_connections,
    )


async def close_redis_client(redis_client: Redis | None) -> None:
    """Close the shared Redis client if it was created."""

    if redis_client is not None:
        await redis_client.aclose()
