from __future__ import annotations

from itertools import count
from typing import Any

from aiogram import Bot
from aiogram.client.session.base import BaseSession
from aiogram.methods import TelegramMethod
from aiogram.types import Message


class FakeTelegramSession(BaseSession):
    """Minimal Bot API stub for local webhook load tests."""

    def __init__(self) -> None:
        super().__init__()
        self._message_ids = count(1)

    async def close(self) -> None:
        return None

    async def make_request(
        self,
        bot: Bot,
        method: TelegramMethod[Any],
        timeout: int | None = None,
    ) -> Any:
        del timeout
        returning = getattr(method, "__returning__", None)
        if returning is bool:
            return True
        if returning is Message:
            return self._build_message(bot, method)
        raise RuntimeError(f"FakeTelegramSession does not support {method.__class__.__name__}")

    async def stream_content(
        self,
        url: str,
        headers: dict[str, Any] | None = None,
        timeout: int = 30,
        chunk_size: int = 65536,
        raise_for_status: bool = True,
    ):
        del url, headers, timeout, chunk_size, raise_for_status
        raise RuntimeError("FakeTelegramSession does not support stream_content")
        yield b""  # pragma: no cover

    def _build_message(self, bot: Bot, method: TelegramMethod[Any]) -> Message:
        chat_id = _int_chat_id(getattr(method, "chat_id", 0))
        text = str(getattr(method, "text", "") or "")
        payload = {
            "message_id": next(self._message_ids),
            "date": 1_720_000_000,
            "chat": {"id": chat_id, "type": "private"},
            "from": {
                "id": 123456789,
                "is_bot": True,
                "first_name": "LoadTestBot",
                "username": "dtb_loadtest_bot",
            },
            "text": text,
        }
        return Message.model_validate(payload, context={"bot": bot})


def _int_chat_id(value: object) -> int:
    if isinstance(value, int):
        return value
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return 0
