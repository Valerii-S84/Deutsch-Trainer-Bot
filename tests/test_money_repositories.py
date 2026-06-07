from __future__ import annotations

from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.base import Base
from app.db.models import Payment, Subscription, User
from app.repositories.payments import PaymentRepository
from app.repositories.subscriptions import SubscriptionRepository
from app.services.entitlements import PLAN_PLUS, PLAN_PRO

NOW = datetime(2026, 5, 15, 10, 0, tzinfo=UTC)


@pytest_asyncio.fixture
async def db_session() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)

    async with engine.begin() as connection:
        await connection.run_sync(
            Base.metadata.create_all,
            tables=[User.__table__, Payment.__table__, Subscription.__table__],
        )

    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with session_factory() as session:
        yield session

    await engine.dispose()


@pytest.mark.asyncio
async def test_payment_repository_charge_lookup_handles_empty_and_provider_only(db_session: AsyncSession) -> None:
    repo = PaymentRepository()
    payment = _payment(1, provider_payment_charge_id="provider-1")
    db_session.add_all([_user(1), payment])
    await db_session.flush()

    empty_lookup = await repo.get_by_charge_id(
        db_session,
        telegram_payment_charge_id=None,
        provider_payment_charge_id=None,
    )
    provider_lookup = await repo.get_by_charge_id(
        db_session,
        telegram_payment_charge_id=None,
        provider_payment_charge_id="provider-1",
    )

    assert empty_lookup is None
    assert provider_lookup is payment


@pytest.mark.asyncio
async def test_payment_repository_mark_paid_can_skip_optional_provider_and_metadata(db_session: AsyncSession) -> None:
    repo = PaymentRepository()
    payment = _payment(1, status="created", audit_metadata={"kept": "value"})
    db_session.add_all([_user(1), payment])
    await db_session.flush()

    paid = await repo.mark_paid(
        db_session,
        payment,
        telegram_payment_charge_id="tg-1",
        provider_payment_charge_id=None,
        paid_at=NOW,
        audit_metadata=None,
    )

    assert paid.status == "paid"
    assert paid.provider_payment_charge_id is None
    assert paid.audit_metadata == {"kept": "value"}


@pytest.mark.asyncio
async def test_payment_repository_mark_cancelled_records_reason(db_session: AsyncSession) -> None:
    repo = PaymentRepository()
    payment = _payment(1, status="created")
    db_session.add_all([_user(1), payment])
    await db_session.flush()

    cancelled = await repo.mark_cancelled(db_session, payment, reason_code="user_cancelled", cancelled_at=NOW)

    assert cancelled.status == "cancelled"
    assert cancelled.cancelled_at == NOW
    assert cancelled.audit_metadata["cancel_reason"] == "user_cancelled"


@pytest.mark.asyncio
async def test_payment_repository_mark_paid_keeps_credited_payment_status(db_session: AsyncSession) -> None:
    repo = PaymentRepository()
    payment = _payment(1, status="credited", audit_metadata={"kept": "value"})
    db_session.add_all([_user(1), payment])
    await db_session.flush()

    paid = await repo.mark_paid(
        db_session,
        payment,
        telegram_payment_charge_id="tg-1",
        provider_payment_charge_id="provider-1",
        paid_at=datetime(2026, 5, 16, 10, 0, tzinfo=UTC),
        audit_metadata={"confirmed": True},
    )

    assert paid.status == "credited"
    assert paid.paid_at is None
    assert paid.audit_metadata == {"kept": "value", "confirmed": True}


@pytest.mark.asyncio
async def test_subscription_repository_prefers_active_credited_pro_over_plus(db_session: AsyncSession) -> None:
    repo = SubscriptionRepository()
    db_session.add(_user(1))
    db_session.add_all(
        [
            _payment(1, plan=PLAN_PLUS, credited_at=NOW),
            _subscription(1, plan=PLAN_PLUS, expires_at=datetime(2026, 7, 1, 10, 0, tzinfo=UTC)),
            _payment(2, plan=PLAN_PRO, credited_at=NOW),
            _subscription(2, plan=PLAN_PRO, expires_at=datetime(2026, 6, 1, 10, 0, tzinfo=UTC)),
        ],
    )
    await db_session.flush()

    subscription = await repo.get_effective_paid_subscription(
        db_session,
        user_id=1,
        now=datetime(2026, 5, 20, 10, 0, tzinfo=UTC),
    )

    assert subscription.plan == PLAN_PRO


@pytest.mark.asyncio
async def test_subscription_repository_lists_latest_user_subscriptions(db_session: AsyncSession) -> None:
    repo = SubscriptionRepository()
    db_session.add(_user(1))
    db_session.add_all(
        [
            _payment(1, plan=PLAN_PLUS),
            _subscription(1, plan=PLAN_PLUS),
            _payment(2, plan=PLAN_PRO),
            _subscription(2, plan=PLAN_PRO),
        ],
    )
    await db_session.flush()

    latest = await repo.get_latest_for_user(db_session, user_id=1)
    subscriptions = await repo.list_user_subscriptions(db_session, user_id=1)

    assert latest.id == 2
    assert [subscription.id for subscription in subscriptions] == [2, 1]


def _user(user_id: int) -> User:
    return User(id=user_id, telegram_user_id=10_000 + user_id)


def _payment(
    payment_id: int,
    *,
    plan: str = PLAN_PLUS,
    status: str = "credited",
    credited_at: datetime | None = NOW,
    provider_payment_charge_id: str | None = None,
    audit_metadata: dict[str, object] | None = None,
) -> Payment:
    return Payment(
        id=payment_id,
        user_id=1,
        plan=plan,
        amount_stars=20 if plan == PLAN_PRO else 10,
        status=status,
        idempotency_key=f"pay-{payment_id}",
        telegram_payment_charge_id=f"tg-{payment_id}" if status in {"paid", "credited"} else None,
        provider_payment_charge_id=provider_payment_charge_id,
        credited_at=credited_at,
        audit_metadata=audit_metadata or {},
    )


def _subscription(
    subscription_id: int,
    *,
    plan: str,
    expires_at: datetime = datetime(2026, 6, 14, 10, 0, tzinfo=UTC),
) -> Subscription:
    return Subscription(
        id=subscription_id,
        user_id=1,
        plan=plan,
        status="active",
        started_at=NOW,
        expires_at=expires_at,
        payment_id=subscription_id,
    )
