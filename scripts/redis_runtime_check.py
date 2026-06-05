#!/usr/bin/env python3
"""Verify live Redis connectivity without touching production state."""

from __future__ import annotations

import asyncio
import os
import uuid

from redis.asyncio import Redis


async def main() -> int:
    redis_url = os.environ.get("REDIS_URL")
    if not redis_url:
        raise SystemExit("REDIS_URL is required for Redis runtime verification")

    key = f"dtb:ci:redis-runtime:{uuid.uuid4().hex}"
    client = Redis.from_url(redis_url)
    try:
        pong = await client.ping()
        if pong is not True:
            raise SystemExit("Redis ping failed")
        await client.set(key, "ok", ex=60)
        value = await client.get(key)
        if value != b"ok":
            raise SystemExit("Redis read/write smoke failed")
        await client.delete(key)
    finally:
        await client.aclose()

    print("[redis_runtime_check] Redis ping and ephemeral read/write passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
