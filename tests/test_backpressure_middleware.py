from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.bot.middlewares.backpressure import BackpressureMiddleware
from app.bot.texts import SATURATION_RETRY_TEXT
from app.runtime.admission import AdmissionBackendError
from app.runtime.backpressure import BackpressureMonitor


class FakeCallback:
    def __init__(self) -> None:
        self.data = "train:ans:1:q:a1"
        self.from_user = SimpleNamespace(id=111)
        self.answer = AsyncMock()


def _update(update_id: int, callback: FakeCallback):
    return SimpleNamespace(update_id=update_id, callback_query=callback)


@pytest.mark.asyncio
async def test_backpressure_rejects_when_global_in_flight_limit_is_full() -> None:
    middleware = BackpressureMiddleware(
        in_flight_limit=1,
        acquire_timeout_seconds=0.001,
        monitor=BackpressureMonitor(),
    )
    await middleware._semaphore.acquire()  # type: ignore[attr-defined]

    second_callback = FakeCallback()
    result = await middleware(lambda event, data: "unexpected", _update(2, second_callback), {})

    middleware._semaphore.release()  # type: ignore[attr-defined]
    assert result is None
    second_callback.answer.assert_awaited_once_with(SATURATION_RETRY_TEXT, show_alert=False)


class FailingAdmissionController:
    limit = 1
    is_shared = True

    async def try_acquire(self, *, timeout_seconds: float):
        raise AdmissionBackendError("redis_admission_unavailable")


class RecordingLease:
    def __init__(self) -> None:
        self.release = AsyncMock()


class RecordingAdmissionController:
    is_shared = True

    def __init__(self, lease: RecordingLease, *, limit: int = 2) -> None:
        self._lease = lease
        self.limit = limit

    async def try_acquire(self, *, timeout_seconds: float):
        return self._lease


@pytest.mark.asyncio
async def test_backpressure_rejects_when_shared_admission_backend_is_unavailable() -> None:
    middleware = BackpressureMiddleware(
        in_flight_limit=1,
        acquire_timeout_seconds=0.001,
        monitor=BackpressureMonitor(),
        admission_controller=FailingAdmissionController(),
    )

    callback = FakeCallback()
    result = await middleware(lambda event, data: "unexpected", _update(2, callback), {})

    assert result is None
    callback.answer.assert_awaited_once_with(SATURATION_RETRY_TEXT, show_alert=False)


@pytest.mark.asyncio
async def test_backpressure_releases_shared_permit_after_handler() -> None:
    lease = RecordingLease()
    controller = RecordingAdmissionController(lease, limit=5)
    middleware = BackpressureMiddleware(
        in_flight_limit=2,
        acquire_timeout_seconds=0.001,
        monitor=BackpressureMonitor(),
        admission_controller=controller,
    )

    async def handler(event, data):
        return "ok"

    result = await middleware(handler, _update(2, FakeCallback()), {})

    assert result == "ok"
    assert middleware.limit == 2
    assert middleware.admission_limit == 5
    lease.release.assert_awaited_once()
