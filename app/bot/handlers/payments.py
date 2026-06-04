"""Telegram Stars payment handlers."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery, LabeledPrice, Message, PreCheckoutQuery

from app.bot.keyboards.subscription import (
    build_invoice_payment_keyboard,
    build_payment_failure_keyboard,
    build_payment_success_keyboard,
    build_subscription_keyboard,
)
from app.bot.texts import (
    CALLBACK_PAYMENT_PLAN_PREFIX,
    PAYMENT_CONFIG_REQUIRED_TEXT,
    PAYMENT_FAILURE_TEXT,
    PAYMENT_PRECHECKOUT_ERROR_TEXT,
    PAYMENT_SUCCESS_PLUS_TEXT,
    PAYMENT_SUCCESS_PRO_TEXT,
)
from app.db.session import get_session as _get_session
from app.services.entitlements import PLAN_PRO
from app.services.payments import (
    PaymentConfigurationError,
    PaymentConfirmation,
    PaymentService,
    PaymentVerificationError,
)

router = Router(name="payments")

_payment_service = PaymentService()


def _session_factory():
    return _get_session()


def _extract_plan(callback_data: str | None) -> str | None:
    if not callback_data or not callback_data.startswith(CALLBACK_PAYMENT_PLAN_PREFIX):
        return None
    plan = callback_data.removeprefix(CALLBACK_PAYMENT_PLAN_PREFIX).lower()
    if plan in {"plus", "pro"}:
        return plan
    return None


@router.callback_query(F.data.startswith(CALLBACK_PAYMENT_PLAN_PREFIX))
async def handle_payment_plan_callback(callback_query: CallbackQuery) -> None:
    await callback_query.answer()
    if callback_query.message is None or callback_query.from_user is None:
        return

    plan = _extract_plan(callback_query.data)
    if plan is None:
        await callback_query.message.answer(
            PAYMENT_CONFIG_REQUIRED_TEXT,
            reply_markup=build_subscription_keyboard(),
        )
        return

    async with _session_factory() as db:
        try:
            invoice = await _payment_service.create_invoice(db, callback_query.from_user.id, plan=plan)
            await db.commit()
        except PaymentConfigurationError:
            await db.rollback()
            await callback_query.message.answer(
                PAYMENT_CONFIG_REQUIRED_TEXT,
                reply_markup=build_subscription_keyboard(),
            )
            return
        except Exception:
            # Payment start must fail closed without exposing provider or config details.
            await db.rollback()
            await callback_query.message.answer(
                PAYMENT_FAILURE_TEXT,
                reply_markup=build_payment_failure_keyboard(plan=plan),
            )
            return

    await callback_query.message.answer_invoice(
        title=invoice.title,
        description=invoice.description,
        payload=invoice.payload,
        currency=invoice.currency,
        prices=[LabeledPrice(label=invoice.price_label, amount=invoice.amount_stars)],
        provider_token=invoice.provider_token,
        reply_markup=build_invoice_payment_keyboard(amount_stars=invoice.amount_stars),
    )


@router.pre_checkout_query()
async def handle_pre_checkout_query(pre_checkout_query: PreCheckoutQuery) -> None:
    async with _session_factory() as db:
        try:
            await _payment_service.verify_pre_checkout(
                db,
                pre_checkout_query.from_user.id,
                invoice_payload=pre_checkout_query.invoice_payload,
                currency=pre_checkout_query.currency,
                total_amount=pre_checkout_query.total_amount,
            )
            await db.commit()
        except (PaymentConfigurationError, PaymentVerificationError):
            await db.rollback()
            await pre_checkout_query.answer(ok=False, error_message=PAYMENT_PRECHECKOUT_ERROR_TEXT)
            return
        except Exception:
            # Provider validation must fail closed with a generic German error.
            await db.rollback()
            await pre_checkout_query.answer(ok=False, error_message=PAYMENT_PRECHECKOUT_ERROR_TEXT)
            return

    await pre_checkout_query.answer(ok=True)


@router.message(F.successful_payment)
async def handle_successful_payment(message: Message) -> None:
    if message.from_user is None or message.successful_payment is None:
        return

    successful_payment = message.successful_payment
    confirmation = PaymentConfirmation(
        invoice_payload=successful_payment.invoice_payload,
        currency=successful_payment.currency,
        total_amount=successful_payment.total_amount,
        telegram_payment_charge_id=successful_payment.telegram_payment_charge_id,
        provider_payment_charge_id=successful_payment.provider_payment_charge_id,
    )
    async with _session_factory() as db:
        try:
            result = await _payment_service.confirm_and_credit_payment(
                db,
                message.from_user.id,
                confirmation,
            )
            await db.commit()
        except (PaymentConfigurationError, PaymentVerificationError):
            await db.rollback()
            await message.answer(PAYMENT_FAILURE_TEXT, reply_markup=build_payment_failure_keyboard())
            return
        except Exception:
            # SuccessfulPayment handling must never unlock access after an unexpected failure.
            await db.rollback()
            await message.answer(PAYMENT_FAILURE_TEXT, reply_markup=build_payment_failure_keyboard())
            return

    text = PAYMENT_SUCCESS_PRO_TEXT if result.payment.plan == PLAN_PRO else PAYMENT_SUCCESS_PLUS_TEXT
    await message.answer(text, reply_markup=build_payment_success_keyboard())
