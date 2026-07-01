from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass


@dataclass
class _LockEntry:
    lock: asyncio.Lock
    refcount: int = 0


_registry_guard = asyncio.Lock()
_locks: dict[str, _LockEntry] = {}


@asynccontextmanager
async def answer_attempt_lock(key: str) -> AsyncIterator[None]:
    async with _registry_guard:
        entry = _locks.get(key)
        if entry is None:
            entry = _LockEntry(asyncio.Lock())
            _locks[key] = entry
        entry.refcount += 1

    await entry.lock.acquire()
    try:
        yield
    finally:
        entry.lock.release()
        async with _registry_guard:
            entry.refcount -= 1
            if entry.refcount <= 0 and not entry.lock.locked():
                _locks.pop(key, None)
