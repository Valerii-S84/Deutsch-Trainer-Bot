"""Abo entrypoint."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from app.bot.keyboards.subscription import build_subscription_keyboard
from app.bot.texts import (
    CALLBACK_SUBSCRIPTION,
    SUBSCRIPTION_STATUS_ACTIVE_TEXT,
    SUBSCRIPTION_STATUS_CANCELLED_TEXT,
    SUBSCRIPTION_STATUS_EXPIRED_TEXT,
    SUBSCRIPTION_STATUS_FAILED_TEXT,
    SUBSCRIPTION_STATUS_FREE_TEXT,
    SUBSCRIPTION_STATUS_INACTIVE_TEXT,
    SUBSCRIPTION_STATUS_PENDING_TEXT,
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
        return _format_subscription_text(
            access_plan=SUBSCRIPTION_STATUS_FREE_TEXT,
            status=SUBSCRIPTION_STATUS_INACTIVE_TEXT,
        )
    status_state = await _entitlement_service.get_subscription_status_state(db, telegram_user_id)
    return _format_subscription_text(
        access_plan=_format_plan(status_state.access_plan),
        status=_format_status(status_state),
    )


def _format_status(status_state) -> str:
    plan = _format_plan(status_state.status_plan)
    expires_at = _format_expiration(status_state.expires_at)
    if status_state.status == "active":
        return SUBSCRIPTION_STATUS_ACTIVE_TEXT.format(plan=plan, expires_at=expires_at)
    if status_state.status == "pending":
        return SUBSCRIPTION_STATUS_PENDING_TEXT.format(plan=plan)
    if status_state.status == "expired":
        return SUBSCRIPTION_STATUS_EXPIRED_TEXT.format(plan=plan, expires_at=expires_at)
    if status_state.status == "cancelled":
        return SUBSCRIPTION_STATUS_CANCELLED_TEXT.format(plan=plan)
    if status_state.status == "failed":
        return SUBSCRIPTION_STATUS_FAILED_TEXT.format(plan=plan)
    return SUBSCRIPTION_STATUS_INACTIVE_TEXT


def _format_expiration(expires_at) -> str:
    if expires_at is None:
        return "unbegrenzt"
    return expires_at.strftime("%d.%m.%Y")


def _format_plan(plan: str) -> str:
    if plan == "plus":
        return "Plus"
    if plan == "pro":
        return "Pro"
    return SUBSCRIPTION_STATUS_FREE_TEXT


def _format_subscription_text(*, access_plan: str, status: str) -> str:
    return SUBSCRIPTION_TEXT.format(access_plan=access_plan, status=status)


@router.message(Command("subscription"))
async def handle_subscription_message(message: Message) -> None:
    try:
        async with _session_factory() as db:
            text = await _subscription_text(db, _extract_user_id(message))
    except Exception:
        text = _format_subscription_text(
            access_plan=SUBSCRIPTION_STATUS_FREE_TEXT,
            status=SUBSCRIPTION_STATUS_INACTIVE_TEXT,
        )
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
                access_plan=SUBSCRIPTION_STATUS_FREE_TEXT,
                status=SUBSCRIPTION_STATUS_INACTIVE_TEXT,
            )
        await callback_query.message.answer(
            text,
            reply_markup=build_subscription_keyboard(),
        )
