from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.bot.handlers import payments
from app.bot.texts import (
    PAYMENT_CONFIG_REQUIRED_TEXT,
    PAYMENT_FAILURE_TEXT,
    PAYMENT_PLAN_CHANGE_BLOCKED_TEXT,
    PAYMENT_PRECHECKOUT_ERROR_TEXT,
    PAYMENT_SUCCESS_PLUS_TEXT,
)
from app.services.payments import PaymentConfigurationError, PaymentVerificationError
from app.services.subscription_credits import PaymentPlanChangeError


class FakeDb:
    def __init__(self) -> None:
        self.committed = 0
        self.rolled_back = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:  # type: ignore[override]
        return None

    async def commit(self) -> None:
        self.committed += 1

    async def rollback(self) -> None:
        self.rolled_back += 1


class FakeMessage:
    def __init__(self, from_user_id: int = 111, successful_payment=None) -> None:
        self.from_user = SimpleNamespace(id=from_user_id)
        self.successful_payment = successful_payment
        self.answer = AsyncMock()
        self.answer_invoice = AsyncMock()


class FakeCallback:
    def __init__(self, data: str = "payment:plan:plus") -> None:
        self.data = data
        self.from_user = SimpleNamespace(id=111)
        self.message = FakeMessage()
        self.answer = AsyncMock()


class FakePreCheckoutQuery:
    def __init__(self, *, payload: str = "payload", amount: int = 100, currency: str = "XTR") -> None:
        self.from_user = SimpleNamespace(id=111)
        self.invoice_payload = payload
        self.total_amount = amount
        self.currency = currency
        self.answer = AsyncMock()


class FakePaymentService:
    def __init__(self, *, should_raise: Exception | None = None) -> None:
        self.should_raise = should_raise
        self.create_invoice_calls: list[tuple[int, str]] = []
        self.verify_calls = 0
        self.credit_calls = 0

    async def create_invoice(self, db, telegram_user_id: int, *, plan: str):
        self.create_invoice_calls.append((telegram_user_id, plan))
        if self.should_raise is not None:
            raise self.should_raise
        return SimpleNamespace(
            title="Plus aktivieren",
            description="Mehr Übungen pro Tag.",
            payload="dtbpay:1:key",
            currency="XTR",
            amount_stars=100,
            price_label="Plus-Abo",
            provider_token="",
        )

    async def verify_pre_checkout(self, db, telegram_user_id: int, **kwargs):
        self.verify_calls += 1
        if self.should_raise is not None:
            raise self.should_raise
        return SimpleNamespace(id=1)

    async def confirm_and_credit_payment(self, db, telegram_user_id: int, confirmation):
        self.credit_calls += 1
        if self.should_raise is not None:
            raise self.should_raise
        return SimpleNamespace(payment=SimpleNamespace(plan="plus"))


def _payloads(markup) -> list[str]:
    return [button.callback_data for row in markup.inline_keyboard for button in row]


@pytest.mark.asyncio
async def test_payment_plan_callback_sends_stars_invoice(monkeypatch) -> None:
    db = FakeDb()
    service = FakePaymentService()
    monkeypatch.setattr(payments, "_session_factory", lambda: db)
    monkeypatch.setattr(payments, "_payment_service", service)

    callback = FakeCallback(data="payment:plan:plus")
    await payments.handle_payment_plan_callback(callback)

    callback.answer.assert_awaited_once()
    callback.message.answer_invoice.assert_awaited_once()
    invoice_kwargs = callback.message.answer_invoice.await_args.kwargs
    assert service.create_invoice_calls == [(111, "plus")]
    assert db.committed == 1
    assert invoice_kwargs["currency"] == "XTR"
    assert invoice_kwargs["provider_token"] == ""
    assert invoice_kwargs["prices"][0].amount == 100
    assert invoice_kwargs["prices"][0].label == "Plus-Abo"
    pay_button = invoice_kwargs["reply_markup"].inline_keyboard[0][0]
    assert pay_button.text == "Bezahlen ⭐ 100"
    assert pay_button.pay is True


@pytest.mark.asyncio
async def test_payment_plan_callback_missing_config_shows_safe_copy(monkeypatch) -> None:
    db = FakeDb()
    service = FakePaymentService(should_raise=PaymentConfigurationError("missing"))
    monkeypatch.setattr(payments, "_session_factory", lambda: db)
    monkeypatch.setattr(payments, "_payment_service", service)

    callback = FakeCallback(data="payment:plan:plus")
    await payments.handle_payment_plan_callback(callback)

    text = callback.message.answer.await_args.args[0]
    assert db.rolled_back == 1
    assert PAYMENT_CONFIG_REQUIRED_TEXT == text
    assert "payment:plan:plus" in _payloads(callback.message.answer.await_args.kwargs["reply_markup"])


@pytest.mark.asyncio
async def test_payment_plan_callback_blocked_downgrade_shows_plan_copy(monkeypatch) -> None:
    db = FakeDb()
    service = FakePaymentService(should_raise=PaymentPlanChangeError("downgrade_not_allowed"))
    monkeypatch.setattr(payments, "_session_factory", lambda: db)
    monkeypatch.setattr(payments, "_payment_service", service)

    callback = FakeCallback(data="payment:plan:plus")
    await payments.handle_payment_plan_callback(callback)

    text = callback.message.answer.await_args.args[0]
    assert db.rolled_back == 1
    assert PAYMENT_PLAN_CHANGE_BLOCKED_TEXT == text
    assert "payment:plan:pro" in _payloads(callback.message.answer.await_args.kwargs["reply_markup"])


@pytest.mark.asyncio
async def test_pre_checkout_accepts_valid_payment(monkeypatch) -> None:
    db = FakeDb()
    service = FakePaymentService()
    monkeypatch.setattr(payments, "_session_factory", lambda: db)
    monkeypatch.setattr(payments, "_payment_service", service)

    query = FakePreCheckoutQuery()
    await payments.handle_pre_checkout_query(query)

    query.answer.assert_awaited_once_with(ok=True)
    assert service.verify_calls == 1
    assert db.committed == 1


@pytest.mark.asyncio
async def test_pre_checkout_rejects_invalid_payment(monkeypatch) -> None:
    db = FakeDb()
    service = FakePaymentService(should_raise=PaymentVerificationError("mismatch"))
    monkeypatch.setattr(payments, "_session_factory", lambda: db)
    monkeypatch.setattr(payments, "_payment_service", service)

    query = FakePreCheckoutQuery()
    await payments.handle_pre_checkout_query(query)

    query.answer.assert_awaited_once_with(ok=False, error_message=PAYMENT_PRECHECKOUT_ERROR_TEXT)
    assert db.rolled_back == 1


@pytest.mark.asyncio
async def test_successful_payment_credits_subscription_and_shows_success(monkeypatch) -> None:
    db = FakeDb()
    service = FakePaymentService()
    monkeypatch.setattr(payments, "_session_factory", lambda: db)
    monkeypatch.setattr(payments, "_payment_service", service)

    successful_payment = SimpleNamespace(
        invoice_payload="dtbpay:1:key",
        currency="XTR",
        total_amount=100,
        telegram_payment_charge_id="tg-1",
        provider_payment_charge_id="provider-1",
    )
    message = FakeMessage(successful_payment=successful_payment)
    await payments.handle_successful_payment(message)

    text = message.answer.await_args.args[0]
    assert service.credit_calls == 1
    assert db.committed == 1
    assert PAYMENT_SUCCESS_PLUS_TEXT == text
    assert "menu:profile" in _payloads(message.answer.await_args.kwargs["reply_markup"])


@pytest.mark.asyncio
async def test_successful_payment_failure_shows_safe_copy(monkeypatch) -> None:
    db = FakeDb()
    service = FakePaymentService(should_raise=PaymentVerificationError("mismatch"))
    monkeypatch.setattr(payments, "_session_factory", lambda: db)
    monkeypatch.setattr(payments, "_payment_service", service)

    successful_payment = SimpleNamespace(
        invoice_payload="dtbpay:1:key",
        currency="XTR",
        total_amount=100,
        telegram_payment_charge_id="tg-1",
        provider_payment_charge_id="provider-1",
    )
    message = FakeMessage(successful_payment=successful_payment)
    await payments.handle_successful_payment(message)

    text = message.answer.await_args.args[0]
    assert db.rolled_back == 1
    assert PAYMENT_FAILURE_TEXT == text
