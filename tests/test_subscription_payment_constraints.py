from __future__ import annotations

from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy import UniqueConstraint, event, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.base import Base
from app.db.models import Payment, Subscription, User


NOW = datetime(2026, 5, 15, 10, 0, tzinfo=UTC)


@pytest_asyncio.fixture
async def db_session() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)

    @event.listens_for(engine.sync_engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    async with engine.begin() as connection:
        await connection.run_sync(
            Base.metadata.create_all,
            tables=[User.__table__, Payment.__table__, Subscription.__table__],
        )

    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with session_factory() as session:
        yield session

    await engine.dispose()


def test_subscription_payment_id_metadata_is_not_nullable() -> None:
    table = Subscription.__table__

    assert table.columns["payment_id"].nullable is False


def test_subscription_payment_id_metadata_has_unique_constraint() -> None:
    table = Subscription.__table__

    assert any(
        isinstance(constraint, UniqueConstraint)
        and constraint.name == "uq_subscriptions_payment_id"
        and set(constraint.columns.keys()) == {"payment_id"}
        for constraint in table.constraints
    )


def test_subscription_payment_id_metadata_references_payments_id() -> None:
    foreign_keys = Subscription.__table__.columns["payment_id"].foreign_keys

    assert any(foreign_key.column.table.name == "payments" for foreign_key in foreign_keys)
    assert any(foreign_key.column.name == "id" for foreign_key in foreign_keys)


@pytest.mark.asyncio
async def test_subscription_with_existing_payment_is_accepted(db_session: AsyncSession) -> None:
    db_session.add_all([_user(1), _payment(10, 1), _subscription(20, 1, 10)])

    await db_session.flush()

    assert await db_session.get(Subscription, 20) is not None


@pytest.mark.asyncio
async def test_duplicate_subscription_payment_id_is_rejected(db_session: AsyncSession) -> None:
    db_session.add_all(
        [
            _user(1),
            _payment(10, 1),
            _subscription(20, 1, 10),
            _subscription(21, 1, 10),
        ],
    )

    with pytest.raises(IntegrityError):
        await db_session.flush()


@pytest.mark.asyncio
async def test_null_subscription_payment_id_is_rejected(db_session: AsyncSession) -> None:
    db_session.add_all([_user(1), _subscription(20, 1, None)])

    with pytest.raises(IntegrityError):
        await db_session.flush()


@pytest.mark.asyncio
async def test_unknown_subscription_payment_id_is_rejected(db_session: AsyncSession) -> None:
    db_session.add_all([_user(1), _subscription(20, 1, 999)])

    with pytest.raises(IntegrityError):
        await db_session.flush()


@pytest.mark.asyncio
async def test_distinct_payments_allow_distinct_subscriptions(db_session: AsyncSession) -> None:
    db_session.add_all(
        [
            _user(1),
            _payment(10, 1),
            _payment(11, 1),
            _subscription(20, 1, 10),
            _subscription(21, 1, 11),
        ],
    )

    await db_session.flush()

    assert await db_session.scalar(select(func.count(Subscription.id))) == 2


def _user(user_id: int) -> User:
    return User(id=user_id, telegram_user_id=10_000 + user_id)


def _payment(payment_id: int, user_id: int) -> Payment:
    return Payment(
        id=payment_id,
        user_id=user_id,
        plan="plus",
        amount_stars=100,
        status="credited",
        idempotency_key=f"pay-{payment_id}",
        telegram_payment_charge_id=f"tg-{payment_id}",
        credited_at=NOW,
    )


def _subscription(subscription_id: int, user_id: int, payment_id: int | None) -> Subscription:
    return Subscription(
        id=subscription_id,
        user_id=user_id,
        plan="plus",
        status="active",
        started_at=NOW,
        expires_at=datetime(2026, 6, 14, 10, 0, tzinfo=UTC),
        payment_id=payment_id,
    )
