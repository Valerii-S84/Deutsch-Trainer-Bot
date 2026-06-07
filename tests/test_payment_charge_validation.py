from __future__ import annotations

from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
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
async def test_empty_telegram_payment_charge_id_is_rejected(db_session: AsyncSession) -> None:
    service = PaymentService(settings=_settings())
    invoice = await _prepared_invoice(service, db_session)

    with pytest.raises(PaymentVerificationError, match="telegram_payment_charge_id_missing"):
        await service.confirm_and_credit_payment(db_session, 111, _confirmation(invoice, telegram_charge_id=""))

    payment = await db_session.get(Payment, invoice.payment_id)
    assert payment.status == "pending"
    assert await db_session.scalar(select(func.count(Subscription.id))) == 0


@pytest.mark.asyncio
async def test_blank_telegram_payment_charge_id_is_rejected(db_session: AsyncSession) -> None:
    service = PaymentService(settings=_settings())
    invoice = await _prepared_invoice(service, db_session)

    with pytest.raises(PaymentVerificationError, match="telegram_payment_charge_id_missing"):
        await service.confirm_and_credit_payment(db_session, 111, _confirmation(invoice, telegram_charge_id="   "))

    assert await db_session.scalar(select(func.count(Subscription.id))) == 0


@pytest.mark.asyncio
async def test_non_string_telegram_payment_charge_id_is_rejected(db_session: AsyncSession) -> None:
    service = PaymentService(settings=_settings())
    invoice = await _prepared_invoice(service, db_session)

    with pytest.raises(PaymentVerificationError, match="telegram_payment_charge_id_missing"):
        await service.confirm_and_credit_payment(db_session, 111, _confirmation(invoice, telegram_charge_id=123))

    assert await db_session.scalar(select(func.count(Subscription.id))) == 0


@pytest.mark.asyncio
async def test_telegram_payment_charge_id_is_trimmed_before_storage(db_session: AsyncSession) -> None:
    service = PaymentService(settings=_settings())
    invoice = await _prepared_invoice(service, db_session)

    result = await service.confirm_and_credit_payment(
        db_session,
        111,
        _confirmation(invoice, telegram_charge_id="  tg-trimmed  ", provider_charge_id="  provider-trimmed  "),
    )

    assert result.payment.telegram_payment_charge_id == "tg-trimmed"
    assert result.payment.provider_payment_charge_id == "provider-trimmed"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("telegram_charge_id", "provider_charge_id"),
    [("tg-no-provider", None), ("tg-blank-provider", "   ")],
)
async def test_optional_provider_payment_charge_id_is_normalized_to_missing(
    db_session: AsyncSession,
    telegram_charge_id: str,
    provider_charge_id: str | None,
) -> None:
    service = PaymentService(settings=_settings())
    invoice = await _prepared_invoice(service, db_session)

    result = await service.confirm_and_credit_payment(
        db_session,
        111,
        _confirmation(invoice, telegram_charge_id=telegram_charge_id, provider_charge_id=provider_charge_id),
    )

    assert result.payment.telegram_payment_charge_id == telegram_charge_id
    assert result.payment.provider_payment_charge_id is None


@pytest.mark.asyncio
async def test_naive_payment_time_is_stored_as_utc(db_session: AsyncSession) -> None:
    service = PaymentService(settings=_settings())
    invoice = await _prepared_invoice(service, db_session)

    payment = await service.confirm_payment(
        db_session,
        111,
        _confirmation(invoice, telegram_charge_id="tg-naive"),
        now=datetime(2026, 5, 15, 10, 0),
    )

    assert payment.paid_at == datetime(2026, 5, 15, 10, 0, tzinfo=UTC)


@pytest.mark.asyncio
async def test_created_payment_allows_missing_telegram_charge_id(db_session: AsyncSession) -> None:
    db_session.add_all([_user(900), _payment(status="created", telegram_payment_charge_id=None)])

    await db_session.flush()

    assert await db_session.get(Payment, 900) is not None


@pytest.mark.asyncio
async def test_paid_payment_requires_non_empty_telegram_charge_id(db_session: AsyncSession) -> None:
    db_session.add_all([_user(900), _payment(status="paid", telegram_payment_charge_id="")])

    with pytest.raises(IntegrityError):
        await db_session.flush()


@pytest.mark.asyncio
async def test_credited_payment_requires_non_empty_telegram_charge_id(db_session: AsyncSession) -> None:
    db_session.add_all([_user(900), _payment(status="credited", telegram_payment_charge_id="   ")])

    with pytest.raises(IntegrityError):
        await db_session.flush()


def _settings() -> Settings:
    return Settings(
        PLUS_PRICE_STARS="10",
        PLUS_DURATION_DAYS=30,
        FREE_DAILY_QUESTION_LIMIT=1,
        PLUS_DAILY_QUESTION_LIMIT=3,
        PRO_DAILY_QUESTION_LIMIT=5,
    )


def _user(user_id: int) -> User:
    return User(id=user_id, telegram_user_id=10_000 + user_id)


async def _prepared_invoice(service: PaymentService, db_session: AsyncSession):
    invoice = await service.create_invoice(db_session, 111, plan=PLAN_PLUS)
    await service.verify_pre_checkout(
        db_session,
        111,
        invoice_payload=invoice.payload,
        currency=invoice.currency,
        total_amount=invoice.amount_stars,
    )
    return invoice


def _confirmation(invoice, *, telegram_charge_id: str, provider_charge_id: str | None = "provider-1") -> PaymentConfirmation:
    return PaymentConfirmation(
        invoice_payload=invoice.payload,
        currency=PAYMENT_CURRENCY,
        total_amount=invoice.amount_stars,
        telegram_payment_charge_id=telegram_charge_id,
        provider_payment_charge_id=provider_charge_id,
    )


def _payment(*, status: str, telegram_payment_charge_id: str | None) -> Payment:
    return Payment(
        id=900,
        user_id=900,
        plan=PLAN_PLUS,
        amount_stars=10,
        status=status,
        idempotency_key=f"pay-{status}",
        telegram_payment_charge_id=telegram_payment_charge_id,
        paid_at=datetime(2026, 5, 15, 10, 0, tzinfo=UTC) if status == "paid" else None,
        credited_at=datetime(2026, 5, 15, 10, 0, tzinfo=UTC) if status == "credited" else None,
    )
