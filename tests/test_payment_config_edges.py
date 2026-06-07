from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import Settings
from app.db.base import Base
from app.db.models import AnalyticsEvent, Payment, Subscription, User
from app.services.entitlements import PLAN_PLUS
from app.services.payments import PaymentConfigurationError, PaymentService


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
    ("price_value", "reason_code"),
    [
        ("not-number", "plus_price_missing"),
        ("0", "plus_price_missing"),
    ],
)
async def test_invalid_runtime_stars_price_blocks_invoice_creation(
    db_session: AsyncSession,
    price_value: str,
    reason_code: str,
) -> None:
    settings = _settings()
    settings.plus_price_stars = price_value
    service = PaymentService(settings=settings)

    with pytest.raises(PaymentConfigurationError) as error:
        await service.create_invoice(db_session, 111, plan=PLAN_PLUS)

    assert error.value.reason_code == reason_code


@pytest.mark.asyncio
async def test_invalid_runtime_duration_blocks_invoice_creation(db_session: AsyncSession) -> None:
    settings = _settings()
    settings.plus_duration_days = 0
    service = PaymentService(settings=settings)

    with pytest.raises(PaymentConfigurationError) as error:
        await service.create_invoice(db_session, 111, plan=PLAN_PLUS)

    assert error.value.reason_code == "plus_duration_missing"


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
