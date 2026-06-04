from __future__ import annotations

import logging
from types import SimpleNamespace
from typing import Any

import pytest

from app.bot.middlewares.logging import LoggingMiddleware


@pytest.mark.asyncio
async def test_logging_middleware_logs_callback_route_without_raw_payload(caplog: pytest.LogCaptureFixture) -> None:
    middleware = LoggingMiddleware()
    callback = SimpleNamespace(
        data="train:ans:10:tok12345:a",
        from_user=SimpleNamespace(id=111),
        message=SimpleNamespace(chat=SimpleNamespace(id=222)),
    )
    update = SimpleNamespace(update_id=333, callback_query=callback, message=None)

    async def handler(event: Any, data: dict[str, Any]) -> str:
        return "ok"

    with caplog.at_level(logging.INFO, logger="app.bot.middlewares.logging"):
        result = await middleware(handler, update, {"event_update": update})

    assert result == "ok"
    assert "callback_route=train:ans" in caplog.text
    assert "tok12345" not in caplog.text
    assert "train:ans:10" not in caplog.text


@pytest.mark.asyncio
async def test_logging_middleware_extracts_message_metadata(caplog: pytest.LogCaptureFixture) -> None:
    middleware = LoggingMiddleware()
    message = SimpleNamespace(
        from_user=SimpleNamespace(id=111),
        chat=SimpleNamespace(id=222),
    )
    update = SimpleNamespace(update_id=333, message=message, callback_query=None)

    async def handler(event: Any, data: dict[str, Any]) -> str:
        return "ok"

    with caplog.at_level(logging.INFO, logger="app.bot.middlewares.logging"):
        await middleware(handler, update, {"event_update": update})

    assert "id=333" in caplog.text
    assert "type=message" in caplog.text
    assert "user_id=111" in caplog.text
    assert "chat_id=222" in caplog.text
