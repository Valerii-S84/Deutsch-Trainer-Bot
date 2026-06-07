from __future__ import annotations

import pytest

from app.bot.handlers import payments
from app.bot.texts import PAYMENT_FAILURE_TEXT, PAYMENT_PRECHECKOUT_ERROR_TEXT, PAYMENT_SUCCESS_PRO_TEXT
from tests.fakes.payment_handlers import (
    FakeDb,
    FakeMessage,
    FakePaymentService,
    FakePreCheckoutQuery,
    successful_payment,
)


@pytest.mark.asyncio
async def test_successful_payment_handler_uses_pro_success_text(monkeypatch) -> None:
    db = FakeDb()
    service = FakePaymentService(result_plan="pro")
    monkeypatch.setattr(payments, "_session_factory", lambda: db)
    monkeypatch.setattr(payments, "_payment_service", service)

    message = FakeMessage(successful_payment=successful_payment(amount=20))
    await payments.handle_successful_payment(message)

    assert service.credit_calls == 1
    assert db.committed == 1
    assert message.answer.await_args.args[0] == PAYMENT_SUCCESS_PRO_TEXT


@pytest.mark.asyncio
async def test_successful_payment_without_user_returns_silently(monkeypatch) -> None:
    monkeypatch.setattr(payments, "_session_factory", _session_must_not_open)

    message = FakeMessage(successful_payment=successful_payment(), has_from_user=False)
    await payments.handle_successful_payment(message)

    message.answer.assert_not_called()


@pytest.mark.asyncio
async def test_successful_payment_without_payment_returns_silently(monkeypatch) -> None:
    monkeypatch.setattr(payments, "_session_factory", _session_must_not_open)

    message = FakeMessage(successful_payment=None)
    await payments.handle_successful_payment(message)

    message.answer.assert_not_called()


@pytest.mark.asyncio
async def test_pre_checkout_unexpected_exception_rolls_back_and_rejects(monkeypatch) -> None:
    db = FakeDb()
    service = FakePaymentService(should_raise=RuntimeError("boom"))
    monkeypatch.setattr(payments, "_session_factory", lambda: db)
    monkeypatch.setattr(payments, "_payment_service", service)

    query = FakePreCheckoutQuery()
    await payments.handle_pre_checkout_query(query)

    assert db.rolled_back == 1
    query.answer.assert_awaited_once_with(ok=False, error_message=PAYMENT_PRECHECKOUT_ERROR_TEXT)


@pytest.mark.asyncio
async def test_successful_payment_unexpected_exception_rolls_back_and_shows_safe_copy(monkeypatch) -> None:
    db = FakeDb()
    service = FakePaymentService(should_raise=RuntimeError("boom"))
    monkeypatch.setattr(payments, "_session_factory", lambda: db)
    monkeypatch.setattr(payments, "_payment_service", service)

    message = FakeMessage(successful_payment=successful_payment())
    await payments.handle_successful_payment(message)

    assert db.rolled_back == 1
    assert message.answer.await_args.args[0] == PAYMENT_FAILURE_TEXT


def _session_must_not_open():
    raise AssertionError("session must not be opened")
