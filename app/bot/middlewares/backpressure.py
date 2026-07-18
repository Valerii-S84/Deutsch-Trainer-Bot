"""Global in-flight limit for Telegram update handling."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.bot.texts import SATURATION_RETRY_TEXT
from app.runtime.backpressure import BackpressureMonitor, global_backpressure_monitor

logger = logging.getLogger(__name__)


class BackpressureMiddleware:
    """Reject updates quickly when the runtime is saturated."""

    def __init__(
        self,
        *,
        in_flight_limit: int,
        acquire_timeout_seconds: float,
        monitor: BackpressureMonitor = global_backpressure_monitor,
    ) -> None:
        self._semaphore = asyncio.Semaphore(in_flight_limit)
        self._acquire_timeout_seconds = max(0.0, acquire_timeout_seconds)
        self._monitor = monitor
        self._monitor.configure(limit=in_flight_limit)

    async def __call__(self, handler: Any, event: Any, data: dict[str, Any]) -> Any:
        update = data.get("event_update") or event
        acquired = await self._try_acquire()
        if not acquired:
            self._monitor.rejected()
            logger.warning("telegram update rejected by global in-flight limit")
            await _notify_saturation(update)
            return None

        try:
            self._monitor.acquired()
            return await handler(event, data)
        finally:
            self._semaphore.release()
            self._monitor.released()

    async def _try_acquire(self) -> bool:
        if getattr(self._semaphore, "_value", 0) <= 0:
            if self._acquire_timeout_seconds == 0:
                return False
            await asyncio.sleep(self._acquire_timeout_seconds)
            if getattr(self._semaphore, "_value", 0) <= 0:
                return False
        await self._semaphore.acquire()
        return True


async def _notify_saturation(update: Any) -> None:
    callback = _callback_query(update)
    if callback is not None and hasattr(callback, "answer"):
        await callback.answer(SATURATION_RETRY_TEXT, show_alert=False)
        return

    message = _message(update)
    if message is not None and hasattr(message, "answer"):
        await message.answer(SATURATION_RETRY_TEXT)


def _message(update: Any) -> Any:
    return getattr(update, "message", None) or _direct_event(update, "text")


def _callback_query(update: Any) -> Any:
    return getattr(update, "callback_query", None) or _direct_event(update, "data")


def _direct_event(update: Any, marker: str) -> Any:
    return update if hasattr(update, marker) and hasattr(update, "from_user") else None
