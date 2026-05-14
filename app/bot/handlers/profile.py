"""Profile / progress entrypoint."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from app.bot.texts import (
    CALLBACK_PROFILE,
    PROFILE_EMPTY_STATE_TEXT,
    PROFILE_PROGRESS_TEMPLATE,
    PROFILE_TEXT,
)
from app.bot.keyboards.main_menu import build_back_to_main_menu_button
from app.db.session import get_session as _get_session
from app.services.progress import ProgressService


router = Router(name="profile")

_progress_service = ProgressService()


def _session_factory():
    return _get_session()


def _format_progress_text(progress_records: list[object]) -> str:
    if not progress_records:
        return f"{PROFILE_TEXT}\n\n{PROFILE_EMPTY_STATE_TEXT}"

    lines = [PROFILE_TEXT, ""]
    for record in progress_records:
        accuracy = getattr(record, "accuracy", 0) or 0
        lines.append(
            PROFILE_PROGRESS_TEMPLATE.format(
                level=getattr(record, "level", "—"),
                theme=getattr(record, "theme", "—") or "—",
                correct=getattr(record, "total_correct", 0),
                answered=getattr(record, "total_answered", 0),
                accuracy=accuracy,
            ),
        )

    return "\n".join(lines)


async def _build_profile_text(db, telegram_user_id: int) -> str:
    try:
        progress_records = await _progress_service.get_user_summary(db, telegram_user_id)
    except Exception:
        progress_records = []
    return _format_progress_text(progress_records)


@router.message(Command("profile"))
async def handle_profile_message(message: Message) -> None:
    user = message.from_user
    if user is None:
        await message.answer(PROFILE_EMPTY_STATE_TEXT, reply_markup=build_back_to_main_menu_button())
        return
    telegram_user_id = getattr(user, "id", None)
    if telegram_user_id is None:
        await message.answer(
            f"{PROFILE_TEXT}\n\n{PROFILE_EMPTY_STATE_TEXT}",
            reply_markup=build_back_to_main_menu_button(),
        )
        return

    try:
        async with _session_factory() as db:
            text = await _build_profile_text(db, telegram_user_id)
    except Exception:
        text = f"{PROFILE_TEXT}\n\n{PROFILE_EMPTY_STATE_TEXT}"
    await message.answer(text, reply_markup=build_back_to_main_menu_button())


@router.callback_query(F.data == CALLBACK_PROFILE)
async def handle_profile_callback(callback_query: CallbackQuery) -> None:
    await callback_query.answer()
    if callback_query.message is not None:
        user = callback_query.from_user
        if user is None:
            await callback_query.message.answer(
                f"{PROFILE_TEXT}\n\n{PROFILE_EMPTY_STATE_TEXT}",
                reply_markup=build_back_to_main_menu_button(),
            )
            return
        telegram_user_id = getattr(user, "id", None)
        if telegram_user_id is None:
            await callback_query.message.answer(
                f"{PROFILE_TEXT}\n\n{PROFILE_EMPTY_STATE_TEXT}",
                reply_markup=build_back_to_main_menu_button(),
            )
            return

        try:
            async with _session_factory() as db:
                text = await _build_profile_text(db, telegram_user_id)
        except Exception:
            text = f"{PROFILE_TEXT}\n\n{PROFILE_EMPTY_STATE_TEXT}"
        await callback_query.message.answer(text, reply_markup=build_back_to_main_menu_button())
