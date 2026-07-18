"""Global in-flight limit for Telegram update handling."""

from __future__ import annotations

import logging
from typing import Any

from app.bot.texts import SATURATION_RETRY_TEXT
from app.runtime.admission import AdmissionBackendError, AdmissionController, LocalAdmissionController
from app.runtime.backpressure import BackpressureMonitor, global_backpressure_monitor
from app.runtime.webhook_profiling import webhook_timing_span

logger = logging.getLogger(__name__)


class BackpressureMiddleware:
    """Reject updates quickly when the runtime is saturated."""

    def __init__(
        self,
        *,
        in_flight_limit: int,
        acquire_timeout_seconds: float,
        monitor: BackpressureMonitor = global_backpressure_monitor,
        admission_controller: AdmissionController | None = None,
    ) -> None:
        self._in_flight_limit = max(1, in_flight_limit)
        self._admission_controller = admission_controller or LocalAdmissionController(limit=in_flight_limit)
        self._semaphore = getattr(self._admission_controller, "semaphore", None)
        self._acquire_timeout_seconds = max(0.0, acquire_timeout_seconds)
        self._monitor = monitor
        self._monitor.configure(limit=self._in_flight_limit)

    async def __call__(self, handler: Any, event: Any, data: dict[str, Any]) -> Any:
        if data.get("skip_backpressure"):
            return await handler(event, data)

        update = data.get("event_update") or event
        try:
            with webhook_timing_span("middleware.backpressure_acquire_ms"):
                lease = await self._admission_controller.try_acquire(timeout_seconds=self._acquire_timeout_seconds)
        except AdmissionBackendError:
            self._monitor.rejected()
            logger.exception("telegram update rejected because shared admission backend is unavailable")
            await _notify_saturation(update)
            return None

        if lease is None:
            self._monitor.rejected()
            logger.warning("telegram update rejected by global in-flight limit")
            await _notify_saturation(update)
            return None

        try:
            self._monitor.acquired()
            return await handler(event, data)
        finally:
            with webhook_timing_span("middleware.backpressure_release_ms"):
                await lease.release()
                self._monitor.released()

    @property
    def limit(self) -> int:
        return self._in_flight_limit

    @property
    def admission_limit(self) -> int:
        return self._admission_controller.limit

    @property
    def uses_shared_admission(self) -> bool:
        return self._admission_controller.is_shared


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
