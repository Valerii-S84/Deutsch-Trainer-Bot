from __future__ import annotations

from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import Settings
from app.db.base import Base
from app.db.models import AnalyticsEvent, Payment, Subscription, User
from app.services.entitlements import FEATURE_FULL_PROGRESS_MAP, EntitlementService, PLAN_FREE, PLAN_PLUS, PLAN_PRO
from app.services.payments import (
    PAYMENT_CURRENCY,
    PaymentConfirmation,
    PaymentConfigurationError,
    PaymentService,
    PaymentVerificationError,
)


@pytest_asyncio.fixture
async def db_session() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)

    async with engine.begin() as connection:
        await connection.run_sync(
            Base.metadata.create_all,
            tables=[
                User.__table__,
                Payment.__table__,
                Subscription.__table__,
                AnalyticsEvent.__table__,
            ],
        )

    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with session_factory() as session:
        yield session

    await engine.dispose()


def _settings() -> Settings:
    return Settings(
        PLUS_PRICE_STARS="100",
        PRO_PRICE_STARS="250",
        PLUS_DURATION_DAYS=30,
        PRO_DURATION_DAYS=90,
        FREE_DAILY_QUESTION_LIMIT=1,
        PLUS_DAILY_QUESTION_LIMIT=3,
        PRO_DAILY_QUESTION_LIMIT=5,
    )


def _confirmation(invoice, *, amount: int | None = None) -> PaymentConfirmation:
    return PaymentConfirmation(
        invoice_payload=invoice.payload,
        currency=PAYMENT_CURRENCY,
        total_amount=amount if amount is not None else invoice.amount_stars,
        telegram_payment_charge_id=f"tg-{invoice.payment_id}",
        provider_payment_charge_id=f"provider-{invoice.payment_id}",
    )


async def _payment_by_id(db_session: AsyncSession, payment_id: int) -> Payment:
    payment = await db_session.get(Payment, payment_id)
    assert payment is not None
    return payment


@pytest.mark.asyncio
async def test_create_invoice_creates_payment_before_invoice(db_session: AsyncSession) -> None:
    service = PaymentService(settings=_settings())

    invoice = await service.create_invoice(db_session, 111, plan=PLAN_PLUS)
    await db_session.flush()

    payment = await _payment_by_id(db_session, invoice.payment_id)
    event_names = [
        event_name
        for event_name, in (
            await db_session.execute(select(AnalyticsEvent.event_name).order_by(AnalyticsEvent.id.asc()))
        ).all()
    ]
    assert invoice.currency == PAYMENT_CURRENCY
    assert invoice.provider_token == ""
    assert invoice.amount_stars == 100
    assert invoice.payload.startswith(f"dtbpay:{payment.id}:")
    assert payment.status == "created"
    assert payment.plan == PLAN_PLUS
    assert payment.amount_stars == 100
    assert payment.audit_metadata["invoice_payload"] == invoice.payload
    assert event_names == ["paywall_clicked", "payment_started"]


@pytest.mark.asyncio
async def test_pre_checkout_marks_payment_pending(db_session: AsyncSession) -> None:
    service = PaymentService(settings=_settings())
    invoice = await service.create_invoice(db_session, 112, plan=PLAN_PLUS)

    payment = await service.verify_pre_checkout(
        db_session,
        112,
        invoice_payload=invoice.payload,
        currency=invoice.currency,
        total_amount=invoice.amount_stars,
    )

    assert payment.status == "pending"


@pytest.mark.asyncio
async def test_pre_checkout_rejects_amount_mismatch(db_session: AsyncSession) -> None:
    service = PaymentService(settings=_settings())
    invoice = await service.create_invoice(db_session, 113, plan=PLAN_PLUS)

    with pytest.raises(PaymentVerificationError):
        await service.verify_pre_checkout(
            db_session,
            113,
            invoice_payload=invoice.payload,
            currency=invoice.currency,
            total_amount=invoice.amount_stars + 1,
        )

    payment = await _payment_by_id(db_session, invoice.payment_id)
    assert payment.status == "created"


@pytest.mark.asyncio
async def test_pre_checkout_rejects_invoice_owned_by_another_user(db_session: AsyncSession) -> None:
    service = PaymentService(settings=_settings())
    invoice = await service.create_invoice(db_session, 119, plan=PLAN_PLUS)

    with pytest.raises(PaymentVerificationError):
        await service.verify_pre_checkout(
            db_session,
            120,
            invoice_payload=invoice.payload,
            currency=invoice.currency,
            total_amount=invoice.amount_stars,
        )

    payment = await _payment_by_id(db_session, invoice.payment_id)
    assert payment.status == "created"


@pytest.mark.asyncio
async def test_payment_success_does_not_unlock_before_credit(db_session: AsyncSession) -> None:
    service = PaymentService(settings=_settings())
    entitlements = EntitlementService(settings=_settings())
    invoice = await service.create_invoice(db_session, 114, plan=PLAN_PLUS)
    await service.verify_pre_checkout(
        db_session,
        114,
        invoice_payload=invoice.payload,
        currency=invoice.currency,
        total_amount=invoice.amount_stars,
    )

    payment = await service.confirm_payment(db_session, 114, _confirmation(invoice))
    decision_before_credit = await entitlements.check_entitlement(
        db_session,
        114,
        feature=FEATURE_FULL_PROGRESS_MAP,
    )

    result = await service.credit_payment(
        db_session,
        payment,
        now=datetime(2026, 5, 15, 10, 0, tzinfo=UTC),
    )
    decision_after_credit = await entitlements.check_entitlement(
        db_session,
        114,
        feature=FEATURE_FULL_PROGRESS_MAP,
        now=datetime(2026, 5, 16, 10, 0, tzinfo=UTC),
    )

    assert payment.status == "credited"
    assert result.subscription.status == "active"
    assert result.subscription.expires_at == datetime(2026, 6, 14, 10, 0, tzinfo=UTC)
    assert decision_before_credit.user_plan == PLAN_FREE
    assert decision_before_credit.allowed is False
    assert decision_after_credit.user_plan == PLAN_PLUS
    assert decision_after_credit.allowed is True


@pytest.mark.asyncio
async def test_duplicate_provider_event_does_not_create_second_subscription(db_session: AsyncSession) -> None:
    service = PaymentService(settings=_settings())
    invoice = await service.create_invoice(db_session, 115, plan=PLAN_PRO)
    confirmation = _confirmation(invoice)

    first = await service.confirm_and_credit_payment(
        db_session,
        115,
        confirmation,
        now=datetime(2026, 5, 15, 10, 0, tzinfo=UTC),
    )
    second = await service.confirm_and_credit_payment(
        db_session,
        115,
        confirmation,
        now=datetime(2026, 5, 15, 10, 5, tzinfo=UTC),
    )

    subscription_count = await db_session.scalar(select(func.count(Subscription.id)))
    event_names = [
        event_name
        for event_name, in (
            await db_session.execute(select(AnalyticsEvent.event_name).order_by(AnalyticsEvent.id.asc()))
        ).all()
    ]
    assert first.duplicate is False
    assert second.duplicate is True
    assert second.subscription.id == first.subscription.id
    assert subscription_count == 1
    assert event_names == ["paywall_clicked", "payment_started", "payment_succeeded", "subscription_started"]


@pytest.mark.asyncio
async def test_duplicate_payload_with_different_provider_reference_is_rejected(db_session: AsyncSession) -> None:
    service = PaymentService(settings=_settings())
    invoice = await service.create_invoice(db_session, 118, plan=PLAN_PLUS)
    confirmation = _confirmation(invoice)
    await service.confirm_and_credit_payment(db_session, 118, confirmation)

    with pytest.raises(PaymentVerificationError):
        await service.confirm_and_credit_payment(
            db_session,
            118,
            PaymentConfirmation(
                invoice_payload=invoice.payload,
                currency=PAYMENT_CURRENCY,
                total_amount=invoice.amount_stars,
                telegram_payment_charge_id="different-tg-charge",
                provider_payment_charge_id="different-provider-charge",
            ),
        )

    subscription_count = await db_session.scalar(select(func.count(Subscription.id)))
    assert subscription_count == 1


@pytest.mark.asyncio
async def test_reused_provider_reference_for_another_payment_is_rejected(db_session: AsyncSession) -> None:
    service = PaymentService(settings=_settings())
    first_invoice = await service.create_invoice(db_session, 121, plan=PLAN_PLUS)
    second_invoice = await service.create_invoice(db_session, 121, plan=PLAN_PRO)
    first_confirmation = _confirmation(first_invoice)
    await service.confirm_and_credit_payment(db_session, 121, first_confirmation)

    with pytest.raises(PaymentVerificationError, match="provider_reference_reused"):
        await service.confirm_and_credit_payment(
            db_session,
            121,
            PaymentConfirmation(
                invoice_payload=second_invoice.payload,
                currency=PAYMENT_CURRENCY,
                total_amount=second_invoice.amount_stars,
                telegram_payment_charge_id=first_confirmation.telegram_payment_charge_id,
                provider_payment_charge_id=first_confirmation.provider_payment_charge_id,
            ),
        )

    subscription_count = await db_session.scalar(select(func.count(Subscription.id)))
    assert subscription_count == 1


@pytest.mark.asyncio
async def test_failed_payment_does_not_unlock_access(db_session: AsyncSession) -> None:
    service = PaymentService(settings=_settings())
    entitlements = EntitlementService(settings=_settings())
    invoice = await service.create_invoice(db_session, 116, plan=PLAN_PLUS)

    payment = await service.mark_failed(db_session, invoice_payload=invoice.payload, reason_code="provider_failed")
    decision = await entitlements.check_entitlement(db_session, 116, feature=FEATURE_FULL_PROGRESS_MAP)

    assert payment.status == "failed"
    assert payment.failed_at is not None
    assert decision.user_plan == PLAN_FREE
    assert decision.allowed is False


@pytest.mark.asyncio
async def test_missing_launch_config_blocks_invoice_creation(db_session: AsyncSession) -> None:
    service = PaymentService(
        settings=Settings(
            PLUS_PRICE_STARS=None,
            PLUS_DURATION_DAYS=None,
        ),
    )

    with pytest.raises(PaymentConfigurationError):
        await service.create_invoice(db_session, 117, plan=PLAN_PLUS)


@pytest.mark.asyncio
async def test_unsupported_plan_blocks_invoice_creation(db_session: AsyncSession) -> None:
    service = PaymentService(settings=_settings())

    with pytest.raises(PaymentConfigurationError, match="unsupported_plan"):
        await service.create_invoice(db_session, 122, plan="enterprise")
