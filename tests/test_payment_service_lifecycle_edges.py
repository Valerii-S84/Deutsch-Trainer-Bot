from __future__ import annotations

from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import Settings
from app.db.base import Base
from app.db.models import AnalyticsEvent, Payment, Subscription, User
from app.services.entitlements import PLAN_PLUS
from app.services.payments import PAYMENT_CURRENCY, PaymentConfirmation, PaymentService, PaymentVerificationError


@pytest_asyncio.fixture
async def db_session() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)

    async with engine.begin() as connection:
        await connection.run_sync(
            Base.metadata.create_all,
            tables=[User.__table__, Payment.__table__, Subscription.__table__, AnalyticsEvent.__table__],
        )

    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with session_factory() as session:
        yield session

    await engine.dispose()


@pytest.mark.asyncio
async def test_pre_checkout_rejects_unknown_idempotency_key(db_session: AsyncSession) -> None:
    service = PaymentService(settings=_settings())

    with pytest.raises(PaymentVerificationError) as error:
        await service.verify_pre_checkout(
            db_session,
            111,
            invoice_payload="dtbpay:1:unknown-key",
            currency=PAYMENT_CURRENCY,
            total_amount=10,
        )

    assert error.value.reason_code == "payment_not_found"


@pytest.mark.asyncio
async def test_pre_checkout_rejects_payload_id_mismatch(db_session: AsyncSession) -> None:
    service = PaymentService(settings=_settings())
    invoice = await service.create_invoice(db_session, 111, plan=PLAN_PLUS)
    _, _, idempotency_key = invoice.payload.split(":")

    with pytest.raises(PaymentVerificationError) as error:
        await service.verify_pre_checkout(
            db_session,
            111,
            invoice_payload=f"dtbpay:{invoice.payment_id + 1}:{idempotency_key}",
            currency=PAYMENT_CURRENCY,
            total_amount=invoice.amount_stars,
        )

    assert error.value.reason_code == "payment_payload_mismatch"


@pytest.mark.asyncio
async def test_pre_checkout_rejects_failed_payment_as_not_payable(db_session: AsyncSession) -> None:
    service = PaymentService(settings=_settings())
    invoice = await service.create_invoice(db_session, 111, plan=PLAN_PLUS)
    await service.mark_failed(db_session, invoice_payload=invoice.payload, reason_code="provider_failed")

    with pytest.raises(PaymentVerificationError) as error:
        await service.verify_pre_checkout(
            db_session,
            111,
            invoice_payload=invoice.payload,
            currency=PAYMENT_CURRENCY,
            total_amount=invoice.amount_stars,
        )

    assert error.value.reason_code == "payment_not_payable"


@pytest.mark.asyncio
async def test_reconfirming_paid_payment_does_not_duplicate_success_event(db_session: AsyncSession) -> None:
    service = PaymentService(settings=_settings())
    invoice = await service.create_invoice(db_session, 111, plan=PLAN_PLUS)
    confirmation = _confirmation(invoice)

    first = await service.confirm_payment(db_session, 111, confirmation)
    second = await service.confirm_payment(db_session, 111, confirmation)

    succeeded_count = await db_session.scalar(
        select(func.count(AnalyticsEvent.id)).where(AnalyticsEvent.event_name == "payment_succeeded"),
    )
    assert first.id == second.id
    assert second.status == "paid"
    assert succeeded_count == 1


@pytest.mark.asyncio
async def test_paid_payment_provider_charge_mismatch_is_rejected(db_session: AsyncSession) -> None:
    service = PaymentService(settings=_settings())
    invoice = await service.create_invoice(db_session, 111, plan=PLAN_PLUS)
    await service.confirm_payment(db_session, 111, _confirmation(invoice, provider_charge_id="provider-1"))

    with pytest.raises(PaymentVerificationError) as error:
        await service.confirm_payment(
            db_session,
            111,
            _confirmation(invoice, provider_charge_id="provider-2"),
        )

    assert error.value.reason_code == "provider_reference_mismatch"


@pytest.mark.asyncio
async def test_credit_payment_rejects_unpaid_payment(db_session: AsyncSession) -> None:
    service = PaymentService(settings=_settings())
    invoice = await service.create_invoice(db_session, 111, plan=PLAN_PLUS)
    payment = await db_session.get(Payment, invoice.payment_id)

    with pytest.raises(PaymentVerificationError) as error:
        await service.credit_payment(db_session, payment)

    assert error.value.reason_code == "payment_not_paid"


@pytest.mark.asyncio
async def test_credit_payment_uses_existing_subscription_for_paid_payment(db_session: AsyncSession) -> None:
    service = PaymentService(settings=_settings())
    invoice = await service.create_invoice(db_session, 111, plan=PLAN_PLUS)
    payment = await service.confirm_payment(db_session, 111, _confirmation(invoice))
    db_session.add(_subscription(payment))
    await db_session.flush()

    result = await service.credit_payment(db_session, payment, now=datetime(2026, 5, 16, 10, 0, tzinfo=UTC))

    assert result.duplicate is False
    assert result.subscription.payment_id == payment.id
    assert result.payment.status == "credited"


@pytest.mark.asyncio
async def test_credited_payment_without_subscription_metadata_is_rejected(db_session: AsyncSession) -> None:
    user = User(id=1, telegram_user_id=111)
    payment = Payment(
        id=1,
        user_id=1,
        plan=PLAN_PLUS,
        amount_stars=10,
        status="credited",
        idempotency_key="pay-1",
        telegram_payment_charge_id="tg-1",
        credited_at=datetime(2026, 5, 15, 10, 0, tzinfo=UTC),
    )
    db_session.add_all([user, payment])
    await db_session.flush()

    with pytest.raises(PaymentVerificationError) as error:
        await PaymentService(settings=_settings()).credit_payment(db_session, payment)

    assert error.value.reason_code == "credited_subscription_missing"


def _settings() -> Settings:
    return Settings(
        PLUS_PRICE_STARS="10",
        PRO_PRICE_STARS="20",
        PLUS_DURATION_DAYS=30,
        PRO_DURATION_DAYS=90,
        FREE_DAILY_QUESTION_LIMIT=1,
        PLUS_DAILY_QUESTION_LIMIT=3,
        PRO_DAILY_QUESTION_LIMIT=5,
    )


def _confirmation(invoice, *, provider_charge_id: str | None = "provider-1") -> PaymentConfirmation:
    return PaymentConfirmation(
        invoice_payload=invoice.payload,
        currency=PAYMENT_CURRENCY,
        total_amount=invoice.amount_stars,
        telegram_payment_charge_id=f"tg-{invoice.payment_id}",
        provider_payment_charge_id=provider_charge_id,
    )


def _subscription(payment: Payment) -> Subscription:
    return Subscription(
        id=payment.id,
        user_id=payment.user_id,
        plan=payment.plan,
        status="active",
        started_at=datetime(2026, 5, 15, 10, 0, tzinfo=UTC),
        expires_at=datetime(2026, 6, 14, 10, 0, tzinfo=UTC),
        payment_id=payment.id,
    )
