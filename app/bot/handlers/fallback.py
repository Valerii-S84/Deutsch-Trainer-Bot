"""Fallback handlers for unknown inputs."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message

from app.bot.texts import UNKNOWN_CALLBACK_TEXT, UNKNOWN_MESSAGE_TEXT

router = Router(name="fallback")


@router.message(F.text)
async def fallback_text(message: Message) -> None:
    """Handle unexpected or non-handled text messages."""
    if not message.text:
        return
    await message.answer(UNKNOWN_MESSAGE_TEXT)


@router.callback_query()
async def fallback_callback(callback_query: CallbackQuery) -> None:
    """Handle stale/unknown callback actions."""
    await callback_query.answer(UNKNOWN_CALLBACK_TEXT, show_alert=True)
