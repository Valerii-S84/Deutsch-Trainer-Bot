"""Owner-only admin metrics entrypoint."""

from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from app.bot.handlers.common import extract_user_id as _extract_user_id
from app.bot.handlers.common import session_factory as _session_factory
from app.bot.texts import ADMIN_METRICS_UNAUTHORIZED_TEXT, ADMIN_METRICS_UNAVAILABLE_TEXT
from app.config import Settings, get_settings
from app.services.analytics import AnalyticsMetricsService, format_admin_metrics

router = Router(name="admin")

_metrics_service = AnalyticsMetricsService()


def _settings() -> Settings:
    return get_settings()


def _is_authorized_admin(telegram_user_id: int | None) -> bool:
    if telegram_user_id is None:
        return False
    return telegram_user_id in set(_settings().admin_telegram_user_ids)


@router.message(Command("admin_metrics"))
async def handle_admin_metrics(message: Message) -> None:
    if not _is_authorized_admin(_extract_user_id(message)):
        await message.answer(ADMIN_METRICS_UNAUTHORIZED_TEXT)
        return

    try:
        async with _session_factory() as db:
            snapshot = await _metrics_service.get_admin_metrics(db)
    except Exception:
        await message.answer(ADMIN_METRICS_UNAVAILABLE_TEXT)
        return

    await message.answer(format_admin_metrics(snapshot))
