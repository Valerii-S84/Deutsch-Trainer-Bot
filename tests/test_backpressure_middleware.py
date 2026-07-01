from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.bot.middlewares.backpressure import BackpressureMiddleware
from app.bot.texts import SATURATION_RETRY_TEXT


class FakeCallback:
    def __init__(self) -> None:
        self.data = "train:ans:1:q:a1"
        self.from_user = SimpleNamespace(id=111)
        self.answer = AsyncMock()


def _update(update_id: int, callback: FakeCallback):
    return SimpleNamespace(update_id=update_id, callback_query=callback)


@pytest.mark.asyncio
async def test_backpressure_rejects_when_global_in_flight_limit_is_full() -> None:
    middleware = BackpressureMiddleware(in_flight_limit=1, acquire_timeout_seconds=0.001)
    await middleware._semaphore.acquire()  # type: ignore[attr-defined]

    second_callback = FakeCallback()
    result = await middleware(lambda event, data: "unexpected", _update(2, second_callback), {})

    middleware._semaphore.release()  # type: ignore[attr-defined]
    assert result is None
    second_callback.answer.assert_awaited_once_with(SATURATION_RETRY_TEXT, show_alert=False)
