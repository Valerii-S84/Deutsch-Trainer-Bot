from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import Settings
from app.db.base import Base
from app.db.models import AnalyticsEvent, Payment, Subscription, User
from app.services.entitlements import PLAN_PLUS
from app.services.payments import PAYMENT_CURRENCY, PaymentService, PaymentVerificationError


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
@pytest.mark.parametrize(
    "payload",
    [
        "wrong:1:key",
        "dtbpay:not-a-number:key",
        "dtbpay:1:",
        "dtbpay:1:key:extra",
    ],
)
async def test_pre_checkout_rejects_malformed_invoice_payloads(db_session: AsyncSession, payload: str) -> None:
    service = PaymentService(settings=_settings())

    with pytest.raises(PaymentVerificationError) as error:
        await service.verify_pre_checkout(
            db_session,
            111,
            invoice_payload=payload,
            currency=PAYMENT_CURRENCY,
            total_amount=10,
        )

    assert error.value.reason_code == "invalid_invoice_payload"


@pytest.mark.asyncio
async def test_pre_checkout_rejects_currency_mismatch_with_reason(db_session: AsyncSession) -> None:
    service = PaymentService(settings=_settings())
    invoice = await service.create_invoice(db_session, 111, plan=PLAN_PLUS)

    with pytest.raises(PaymentVerificationError) as error:
        await service.verify_pre_checkout(
            db_session,
            111,
            invoice_payload=invoice.payload,
            currency="EUR",
            total_amount=invoice.amount_stars,
        )

    payment = await db_session.get(Payment, invoice.payment_id)
    assert error.value.reason_code == "payment_currency_mismatch"
    assert payment.status == "created"


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
