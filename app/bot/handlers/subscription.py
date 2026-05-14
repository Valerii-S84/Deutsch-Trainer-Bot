"""Abo entrypoint."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from app.bot.keyboards.subscription import build_subscription_keyboard
from app.bot.texts import (
    CALLBACK_SUBSCRIPTION,
    SUBSCRIPTION_STATUS_ACTIVE_TEXT,
    SUBSCRIPTION_STATUS_FREE_TEXT,
    SUBSCRIPTION_STATUS_INACTIVE_TEXT,
    SUBSCRIPTION_TEXT,
)
from app.db.session import get_session as _get_session
from app.services.entitlements import EntitlementService

router = Router(name="subscription")

_entitlement_service = EntitlementService()


def _session_factory():
    return _get_session()


def _extract_user_id(event: Message | CallbackQuery) -> int | None:
    return getattr(getattr(event, "from_user", None), "id", None)


async def _subscription_text(db, telegram_user_id: int | None) -> str:
    if telegram_user_id is None:
        return _format_subscription_text(plan=SUBSCRIPTION_STATUS_FREE_TEXT, status=SUBSCRIPTION_STATUS_INACTIVE_TEXT)
    access_state = await _entitlement_service.get_access_state(db, telegram_user_id)
    subscription = access_state.subscription
    if subscription is None:
        return _format_subscription_text(plan=SUBSCRIPTION_STATUS_FREE_TEXT, status=SUBSCRIPTION_STATUS_INACTIVE_TEXT)
    expires_at = subscription.expires_at.strftime("%d.%m.%Y") if subscription.expires_at else "unbegrenzt"
    return _format_subscription_text(
        plan=subscription.plan.upper(),
        status=SUBSCRIPTION_STATUS_ACTIVE_TEXT.format(expires_at=expires_at),
    )


def _format_subscription_text(*, plan: str, status: str) -> str:
    return SUBSCRIPTION_TEXT.format(plan=plan, status=status)


@router.message(Command("subscription"))
async def handle_subscription_message(message: Message) -> None:
    try:
        async with _session_factory() as db:
            text = await _subscription_text(db, _extract_user_id(message))
    except Exception:
        text = _format_subscription_text(plan=SUBSCRIPTION_STATUS_FREE_TEXT, status=SUBSCRIPTION_STATUS_INACTIVE_TEXT)
    await message.answer(text, reply_markup=build_subscription_keyboard())


@router.callback_query(F.data == CALLBACK_SUBSCRIPTION)
async def handle_subscription_callback(callback_query: CallbackQuery) -> None:
    await callback_query.answer()
    if callback_query.message is not None:
        try:
            async with _session_factory() as db:
                text = await _subscription_text(db, _extract_user_id(callback_query))
        except Exception:
            text = _format_subscription_text(
                plan=SUBSCRIPTION_STATUS_FREE_TEXT,
                status=SUBSCRIPTION_STATUS_INACTIVE_TEXT,
            )
        await callback_query.message.answer(
            text,
            reply_markup=build_subscription_keyboard(),
        )
