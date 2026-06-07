from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from app.bot.handlers import common as handler_common
from app.config import Settings
from app.db.models import Payment
from app.repositories.sqlite_compat import next_sqlite_id_if_needed
from app.services.entitlements import PLAN_PLUS
from app.services.payments import PAYMENT_CURRENCY, PaymentConfirmation, PaymentService, PaymentVerificationError

NOW = datetime(2026, 5, 15, 10, 0, tzinfo=UTC)


def test_payment_session_factory_uses_configured_get_session(monkeypatch) -> None:
    session = object()
    monkeypatch.setattr(handler_common, "get_session", lambda: session)

    assert handler_common.session_factory() is session


@pytest.mark.asyncio
async def test_repository_next_id_returns_none_outside_sqlite() -> None:
    db = SimpleNamespace(get_bind=lambda: SimpleNamespace(dialect=SimpleNamespace(name="postgresql")))

    assert await next_sqlite_id_if_needed(db, Payment) is None


@pytest.mark.asyncio
async def test_repository_next_id_returns_next_sqlite_id() -> None:
    db = FakeSqliteDb(max_id=41)

    assert await next_sqlite_id_if_needed(db, Payment) == 42


@pytest.mark.asyncio
async def test_repository_next_id_starts_at_one_for_empty_sqlite_table() -> None:
    db = FakeSqliteDb(max_id=None)

    assert await next_sqlite_id_if_needed(db, Payment) == 1


@pytest.mark.asyncio
async def test_create_invoice_flushes_new_user_and_handles_db_without_flush() -> None:
    user = SimpleNamespace(id=None)
    db = FakeDb(user=user)
    service = _payment_service(user=user)

    invoice = await service.create_invoice(db, 111, plan=PLAN_PLUS)
    no_flush_invoice = await _payment_service(user=SimpleNamespace(id=88)).create_invoice(object(), 111, plan=PLAN_PLUS)

    assert db.flushed == 2
    assert invoice.payload.startswith("dtbpay:5:")
    assert no_flush_invoice.payload.startswith("dtbpay:5:")


@pytest.mark.asyncio
async def test_confirm_payment_rejects_not_confirmable_status() -> None:
    payment = _payment(status="cancelled")
    service = _payment_service(user=SimpleNamespace(id=1), payment=payment)

    with pytest.raises(PaymentVerificationError) as error:
        await service.confirm_payment(None, 111, _confirmation())

    assert error.value.reason_code == "payment_not_confirmable"


class FakeDb:
    def __init__(self, *, user) -> None:
        self.user = user
        self.flushed = 0

    async def flush(self) -> None:
        self.flushed += 1
        if self.user.id is None:
            self.user.id = 77


class FakeSqliteDb:
    def __init__(self, *, max_id: int | None) -> None:
        self.max_id = max_id

    def get_bind(self):
        return SimpleNamespace(dialect=SimpleNamespace(name="sqlite"))

    async def scalar(self, _query):
        return self.max_id


class FakeUserRepo:
    def __init__(self, user) -> None:
        self.user = user

    async def create_if_missing(self, db, telegram_user_id: int):
        return self.user

    async def get_by_telegram_id(self, db, telegram_user_id: int):
        return self.user


class FakePaymentRepo:
    def __init__(self, payment: Payment | None = None) -> None:
        self.payment = payment

    async def create(self, db, **kwargs):
        return SimpleNamespace(id=5, audit_metadata={})

    async def get_by_idempotency_key(self, db, *, idempotency_key: str):
        return self.payment

    async def get_by_charge_id(self, db, **kwargs):
        return None


class FakeSubscriptionRepo:
    async def get_effective_paid_subscription(self, db, *, user_id: int, now=None):
        return None

    async def get_latest_for_user(self, db, *, user_id: int):
        return None


class FakeAnalyticsRepo:
    async def record(self, db, **kwargs):
        return SimpleNamespace(**kwargs)


def _payment_service(*, user, payment: Payment | None = None) -> PaymentService:
    return PaymentService(
        user_repo=FakeUserRepo(user),
        payment_repo=FakePaymentRepo(payment),
        subscription_repo=FakeSubscriptionRepo(),
        analytics_repo=FakeAnalyticsRepo(),
        settings=_settings(),
    )


def _payment(*, status: str) -> Payment:
    return Payment(
        id=1,
        user_id=1,
        plan=PLAN_PLUS,
        amount_stars=10,
        status=status,
        idempotency_key="key",
    )


def _confirmation() -> PaymentConfirmation:
    return PaymentConfirmation(
        invoice_payload="dtbpay:1:key",
        currency=PAYMENT_CURRENCY,
        total_amount=10,
        telegram_payment_charge_id="tg-1",
        provider_payment_charge_id=None,
    )


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
