from __future__ import annotations

import pytest

from app.bot.handlers import payments
from app.bot.texts import PAYMENT_CONFIG_REQUIRED_TEXT, PAYMENT_FAILURE_TEXT
from tests.fakes.payment_handlers import FakeCallback, FakeDb, FakePaymentService, callback_payloads


@pytest.mark.asyncio
async def test_pro_plan_callback_sends_pro_stars_invoice(monkeypatch) -> None:
    db = FakeDb()
    service = FakePaymentService()
    monkeypatch.setattr(payments, "_session_factory", lambda: db)
    monkeypatch.setattr(payments, "_payment_service", service)

    callback = FakeCallback(data="payment:plan:pro")
    await payments.handle_payment_plan_callback(callback)

    invoice_kwargs = callback.message.answer_invoice.await_args.kwargs
    pay_button = invoice_kwargs["reply_markup"].inline_keyboard[0][0]
    assert service.create_invoice_calls == [(111, "pro")]
    assert db.committed == 1
    assert invoice_kwargs["prices"][0].amount == 20
    assert invoice_kwargs["prices"][0].label == "Pro-Abo"
    assert pay_button.text == "Bezahlen ⭐ 20"
    assert pay_button.pay is True


@pytest.mark.asyncio
async def test_invalid_plan_callback_shows_config_copy_without_session(monkeypatch) -> None:
    service = FakePaymentService()
    monkeypatch.setattr(payments, "_session_factory", _session_must_not_open)
    monkeypatch.setattr(payments, "_payment_service", service)

    callback = FakeCallback(data="payment:plan:enterprise")
    await payments.handle_payment_plan_callback(callback)

    answer_kwargs = callback.message.answer.await_args.kwargs
    assert callback.message.answer.await_args.args[0] == PAYMENT_CONFIG_REQUIRED_TEXT
    assert service.create_invoice_calls == []
    assert "payment:plan:plus" in callback_payloads(answer_kwargs["reply_markup"])
    assert "payment:plan:pro" in callback_payloads(answer_kwargs["reply_markup"])


@pytest.mark.asyncio
async def test_payment_plan_callback_without_message_returns_after_answer(monkeypatch) -> None:
    monkeypatch.setattr(payments, "_session_factory", _session_must_not_open)

    callback = FakeCallback(has_message=False)
    await payments.handle_payment_plan_callback(callback)

    callback.answer.assert_awaited_once()


@pytest.mark.asyncio
async def test_payment_plan_callback_without_user_returns_after_answer(monkeypatch) -> None:
    monkeypatch.setattr(payments, "_session_factory", _session_must_not_open)

    callback = FakeCallback(has_from_user=False)
    await payments.handle_payment_plan_callback(callback)

    callback.answer.assert_awaited_once()
    callback.message.answer.assert_not_called()
    callback.message.answer_invoice.assert_not_called()


@pytest.mark.asyncio
async def test_payment_plan_callback_unexpected_exception_rolls_back(monkeypatch) -> None:
    db = FakeDb()
    service = FakePaymentService(should_raise=RuntimeError("boom"))
    monkeypatch.setattr(payments, "_session_factory", lambda: db)
    monkeypatch.setattr(payments, "_payment_service", service)

    callback = FakeCallback(data="payment:plan:plus")
    await payments.handle_payment_plan_callback(callback)

    answer_kwargs = callback.message.answer.await_args.kwargs
    assert db.rolled_back == 1
    assert callback.message.answer.await_args.args[0] == PAYMENT_FAILURE_TEXT
    assert "payment:plan:plus" in callback_payloads(answer_kwargs["reply_markup"])


def _session_must_not_open():
    raise AssertionError("session must not be opened")


def test_extract_plan_rejects_empty_or_wrong_prefix_payload() -> None:
    assert payments._extract_plan(None) is None
    assert payments._extract_plan("menu:subscription") is None
