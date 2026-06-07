from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock


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
    def __init__(
        self,
        *,
        from_user_id: int = 111,
        successful_payment=None,
        has_from_user: bool = True,
    ) -> None:
        self.from_user = SimpleNamespace(id=from_user_id) if has_from_user else None
        self.successful_payment = successful_payment
        self.answer = AsyncMock()
        self.answer_invoice = AsyncMock()


class FakeCallback:
    def __init__(
        self,
        *,
        data: str = "payment:plan:plus",
        from_user_id: int = 111,
        has_message: bool = True,
        has_from_user: bool = True,
    ) -> None:
        self.data = data
        self.from_user = SimpleNamespace(id=from_user_id) if has_from_user else None
        self.message = FakeMessage(from_user_id=from_user_id) if has_message else None
        self.answer = AsyncMock()


class FakePreCheckoutQuery:
    def __init__(self, *, payload: str = "payload", amount: int = 10, currency: str = "XTR") -> None:
        self.from_user = SimpleNamespace(id=111)
        self.invoice_payload = payload
        self.total_amount = amount
        self.currency = currency
        self.answer = AsyncMock()


class FakePaymentService:
    def __init__(self, *, should_raise: Exception | None = None, result_plan: str = "plus") -> None:
        self.should_raise = should_raise
        self.result_plan = result_plan
        self.create_invoice_calls: list[tuple[int, str]] = []
        self.verify_calls = 0
        self.credit_calls = 0

    async def create_invoice(self, db, telegram_user_id: int, *, plan: str):
        self.create_invoice_calls.append((telegram_user_id, plan))
        if self.should_raise is not None:
            raise self.should_raise
        amount_stars = 20 if plan == "pro" else 10
        return SimpleNamespace(
            title=f"{plan.capitalize()} aktivieren",
            description=f"{plan.capitalize()} aktivieren.",
            payload=f"dtbpay:1:{plan}",
            currency="XTR",
            amount_stars=amount_stars,
            price_label=f"{plan.capitalize()}-Abo",
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
        return SimpleNamespace(payment=SimpleNamespace(plan=self.result_plan))


def successful_payment(*, amount: int = 10):
    return SimpleNamespace(
        invoice_payload="dtbpay:1:key",
        currency="XTR",
        total_amount=amount,
        telegram_payment_charge_id="tg-1",
        provider_payment_charge_id="provider-1",
    )


def callback_payloads(markup) -> list[str]:
    return [button.callback_data for row in markup.inline_keyboard for button in row]
