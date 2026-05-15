from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from app.config import Settings, get_settings
from app.db.models import Payment, Subscription
from app.repositories.analytics_events import AnalyticsEventRepository
from app.repositories.payments import PaymentRepository
from app.repositories.subscriptions import SubscriptionRepository
from app.repositories.users import UserRepository
from app.services.analytics import AnalyticsTracker
from app.services.entitlements import PLAN_PLUS, PLAN_PRO

PAYMENT_CURRENCY = "XTR"
PAYMENT_PROVIDER = "telegram_stars"
PAYMENT_PROVIDER_TOKEN = ""
PAYMENT_PAYLOAD_PREFIX = "dtbpay"
SUPPORTED_PAYMENT_PLANS = {PLAN_PLUS, PLAN_PRO}


@dataclass(frozen=True)
class PaymentPlanConfig:
    plan: str
    amount_stars: int
    duration_days: int
    title: str
    description: str
    config_reference: str


@dataclass(frozen=True)
class PaymentInvoice:
    payment_id: int
    plan: str
    title: str
    description: str
    payload: str
    currency: str
    amount_stars: int
    price_label: str
    provider_token: str


@dataclass(frozen=True)
class PaymentConfirmation:
    invoice_payload: str
    currency: str
    total_amount: int
    telegram_payment_charge_id: str
    provider_payment_charge_id: str | None = None


@dataclass(frozen=True)
class PaymentCreditResult:
    payment: Payment
    subscription: Subscription
    duplicate: bool


class PaymentConfigurationError(Exception):
    """Raised when payment launch config is missing or invalid."""

    def __init__(self, reason_code: str) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


class PaymentVerificationError(Exception):
    """Raised when provider payment data does not match the expected payment."""

    def __init__(self, reason_code: str) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


class PaymentService:
    """Telegram Stars payment lifecycle and idempotent subscription crediting."""

    def __init__(
        self,
        *,
        user_repo: UserRepository | None = None,
        payment_repo: PaymentRepository | None = None,
        subscription_repo: SubscriptionRepository | None = None,
        analytics_repo: AnalyticsEventRepository | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._user_repo = user_repo or UserRepository()
        self._payment_repo = payment_repo or PaymentRepository()
        self._subscription_repo = subscription_repo or SubscriptionRepository()
        self._analytics_repo = analytics_repo or AnalyticsEventRepository()
        self._analytics_tracker = AnalyticsTracker(self._analytics_repo)
        self._settings = settings or get_settings()

    async def create_invoice(self, db, telegram_user_id: int, *, plan: str) -> PaymentInvoice:
        config = self._plan_config(plan)
        user = await self._user_repo.create_if_missing(db, telegram_user_id)
        if getattr(user, "id", None) is None and hasattr(db, "flush"):
            await db.flush()

        idempotency_key = uuid4().hex
        payment = await self._payment_repo.create(
            db,
            user_id=user.id,
            plan=config.plan,
            amount_stars=config.amount_stars,
            idempotency_key=idempotency_key,
            config_reference=config.config_reference,
            audit_metadata={
                "provider": PAYMENT_PROVIDER,
                "telegram_stars_mode": self._settings.telegram_stars_mode,
                "plan": config.plan,
                "amount_stars": config.amount_stars,
                "duration_days": config.duration_days,
            },
        )
        if hasattr(db, "flush"):
            await db.flush()

        payload = _build_invoice_payload(payment.id, idempotency_key)
        payment.audit_metadata = {
            **(payment.audit_metadata or {}),
            "invoice_payload": payload,
        }
        current_subscription = await self._subscription_repo.get_effective_paid_subscription(db, user_id=user.id)
        current_plan = current_subscription.plan if current_subscription is not None else "free"
        await self._record_event(
            db,
            event_name="paywall_clicked",
            user_id=user.id,
            metadata={
                "cta_id": f"payment_plan_{config.plan}",
                "plan_offered": config.plan,
                "user_plan": current_plan,
            },
        )
        await self._record_event(
            db,
            event_name="payment_started",
            user_id=user.id,
            metadata={
                "payment_id": payment.id,
                "plan": config.plan,
                "amount_stars": config.amount_stars,
                "config_reference": config.config_reference,
                "provider": PAYMENT_PROVIDER,
            },
        )
        return PaymentInvoice(
            payment_id=payment.id,
            plan=config.plan,
            title=config.title,
            description=config.description,
            payload=payload,
            currency=PAYMENT_CURRENCY,
            amount_stars=config.amount_stars,
            price_label=f"{config.plan.capitalize()}",
            provider_token=PAYMENT_PROVIDER_TOKEN,
        )

    async def verify_pre_checkout(
        self,
        db,
        telegram_user_id: int,
        *,
        invoice_payload: str,
        currency: str,
        total_amount: int,
    ) -> Payment:
        payment = await self._payment_from_payload(db, invoice_payload)
        await self._verify_payment_owner(db, payment, telegram_user_id)
        self._verify_payment_config(payment, currency=currency, total_amount=total_amount)
        if payment.status not in {"created", "pending"}:
            raise PaymentVerificationError("payment_not_payable")
        return await self._payment_repo.mark_pending(db, payment)

    async def confirm_payment(
        self,
        db,
        telegram_user_id: int,
        confirmation: PaymentConfirmation,
        *,
        now: datetime | None = None,
    ) -> Payment:
        payment = await self._payment_from_payload(db, confirmation.invoice_payload)
        existing = await self._payment_repo.get_by_charge_id(
            db,
            telegram_payment_charge_id=confirmation.telegram_payment_charge_id,
            provider_payment_charge_id=confirmation.provider_payment_charge_id,
        )
        if existing is not None and existing.id != payment.id:
            raise PaymentVerificationError("provider_reference_reused")

        await self._verify_payment_owner(db, payment, telegram_user_id)
        self._verify_payment_config(
            payment,
            currency=confirmation.currency,
            total_amount=confirmation.total_amount,
        )
        if payment.status == "credited":
            if not _charge_ids_match(payment, confirmation):
                raise PaymentVerificationError("provider_reference_mismatch")
            return payment
        if payment.status not in {"created", "pending", "paid"}:
            raise PaymentVerificationError("payment_not_confirmable")
        if not _charge_ids_match(payment, confirmation):
            raise PaymentVerificationError("provider_reference_mismatch")

        previous_status = payment.status
        paid = await self._payment_repo.mark_paid(
            db,
            payment,
            telegram_payment_charge_id=confirmation.telegram_payment_charge_id,
            provider_payment_charge_id=confirmation.provider_payment_charge_id,
            paid_at=_as_aware_utc(now or datetime.now(UTC)),
            audit_metadata={
                "confirmed_currency": confirmation.currency,
                "confirmed_total_amount": confirmation.total_amount,
            },
        )
        if previous_status in {"created", "pending"}:
            await self._record_event(
                db,
                event_name="payment_succeeded",
                user_id=paid.user_id,
                metadata={
                    "payment_id": paid.id,
                    "plan": paid.plan,
                    "amount_stars": paid.amount_stars,
                    "provider": PAYMENT_PROVIDER,
                },
            )
        return paid

    async def credit_payment(
        self,
        db,
        payment: Payment,
        *,
        now: datetime | None = None,
    ) -> PaymentCreditResult:
        existing_subscription = await self._subscription_repo.get_by_payment_id(db, payment_id=payment.id)
        if payment.status == "credited":
            if existing_subscription is None:
                raise PaymentVerificationError("credited_subscription_missing")
            return PaymentCreditResult(payment=payment, subscription=existing_subscription, duplicate=True)
        if payment.status != "paid":
            raise PaymentVerificationError("payment_not_paid")

        config = self._plan_config(payment.plan)
        started_at = _as_aware_utc(now or datetime.now(UTC))
        expires_at = started_at + timedelta(days=config.duration_days)
        subscription = existing_subscription
        if subscription is None:
            subscription = await self._subscription_repo.create_active_from_payment(
                db,
                user_id=payment.user_id,
                plan=payment.plan,
                payment_id=payment.id,
                started_at=started_at,
                expires_at=expires_at,
                provider_reference=payment.telegram_payment_charge_id or payment.provider_payment_charge_id,
            )
            await self._record_event(
                db,
                event_name="subscription_started",
                user_id=payment.user_id,
                metadata={
                    "payment_id": payment.id,
                    "plan": payment.plan,
                    "previous_plan": "free",
                    "provider": PAYMENT_PROVIDER,
                    "started_at": started_at.isoformat(),
                    "expires_at": expires_at.isoformat(),
                },
            )
        await self._payment_repo.mark_credited(db, payment, credited_at=started_at)
        return PaymentCreditResult(payment=payment, subscription=subscription, duplicate=False)

    async def confirm_and_credit_payment(
        self,
        db,
        telegram_user_id: int,
        confirmation: PaymentConfirmation,
        *,
        now: datetime | None = None,
    ) -> PaymentCreditResult:
        payment = await self.confirm_payment(db, telegram_user_id, confirmation, now=now)
        return await self.credit_payment(db, payment, now=now)

    async def mark_failed(
        self,
        db,
        *,
        invoice_payload: str,
        reason_code: str,
        now: datetime | None = None,
    ) -> Payment:
        payment = await self._payment_from_payload(db, invoice_payload)
        failed = await self._payment_repo.mark_failed(
            db,
            payment,
            failed_at=_as_aware_utc(now or datetime.now(UTC)),
            reason_code=reason_code,
        )
        await self._record_event(
            db,
            event_name="payment_failed",
            user_id=failed.user_id,
            metadata={
                "payment_id": failed.id,
                "plan": failed.plan,
                "reason_code": reason_code,
                "provider": PAYMENT_PROVIDER,
            },
        )
        return failed

    def _plan_config(self, plan: str) -> PaymentPlanConfig:
        normalized_plan = str(plan).lower()
        if normalized_plan not in SUPPORTED_PAYMENT_PLANS:
            raise PaymentConfigurationError("unsupported_plan")
        if normalized_plan == PLAN_PLUS:
            amount = _required_positive_int(self._settings.plus_price_stars, "plus_price_missing")
            duration = _required_positive_int(self._settings.plus_duration_days, "plus_duration_missing")
            return PaymentPlanConfig(
                plan=PLAN_PLUS,
                amount_stars=amount,
                duration_days=duration,
                title="Plus aktivieren",
                description="Mehr Übungen pro Tag, vollständiger Fortschritt und gezielte Fehlerwiederholung.",
                config_reference=f"plus:{amount}:stars:{duration}:days",
            )

        amount = _required_positive_int(self._settings.pro_price_stars, "pro_price_missing")
        duration = _required_positive_int(self._settings.pro_duration_days, "pro_duration_missing")
        return PaymentPlanConfig(
            plan=PLAN_PRO,
            amount_stars=amount,
            duration_days=duration,
            title="Pro aktivieren",
            description="Erweiterte Statistik, mehr Training und ein tieferer Fehlerüberblick.",
            config_reference=f"pro:{amount}:stars:{duration}:days",
        )

    async def _payment_from_payload(self, db, invoice_payload: str) -> Payment:
        payment_id, idempotency_key = _parse_invoice_payload(invoice_payload)
        payment = await self._payment_repo.get_by_idempotency_key(db, idempotency_key=idempotency_key)
        if payment is None:
            raise PaymentVerificationError("payment_not_found")
        if payment.id != payment_id:
            raise PaymentVerificationError("payment_payload_mismatch")
        return payment

    async def _verify_payment_owner(self, db, payment: Payment, telegram_user_id: int) -> None:
        user = await self._user_repo.get_by_telegram_id(db, telegram_user_id)
        if user is None or user.id != payment.user_id:
            raise PaymentVerificationError("payment_user_mismatch")

    def _verify_payment_config(self, payment: Payment, *, currency: str, total_amount: int) -> None:
        if currency != PAYMENT_CURRENCY:
            raise PaymentVerificationError("payment_currency_mismatch")
        config = self._plan_config(payment.plan)
        if payment.amount_stars != config.amount_stars or total_amount != config.amount_stars:
            raise PaymentVerificationError("payment_amount_mismatch")

    async def _record_event(
        self,
        db,
        *,
        event_name: str,
        user_id: int,
        metadata: dict[str, object],
    ) -> None:
        await self._analytics_tracker.record(
            db,
            event_name=event_name,
            user_id=user_id,
            event_metadata=metadata,
            source="payments",
        )


def _build_invoice_payload(payment_id: int, idempotency_key: str) -> str:
    return f"{PAYMENT_PAYLOAD_PREFIX}:{payment_id}:{idempotency_key}"


def _parse_invoice_payload(invoice_payload: str) -> tuple[int, str]:
    parts = invoice_payload.split(":")
    if len(parts) != 3 or parts[0] != PAYMENT_PAYLOAD_PREFIX:
        raise PaymentVerificationError("invalid_invoice_payload")
    try:
        payment_id = int(parts[1])
    except ValueError as exc:
        raise PaymentVerificationError("invalid_invoice_payload") from exc
    idempotency_key = parts[2]
    if not idempotency_key:
        raise PaymentVerificationError("invalid_invoice_payload")
    return payment_id, idempotency_key


def _charge_ids_match(payment: Payment, confirmation: PaymentConfirmation) -> bool:
    if (
        payment.telegram_payment_charge_id
        and payment.telegram_payment_charge_id != confirmation.telegram_payment_charge_id
    ):
        return False
    if (
        payment.provider_payment_charge_id
        and confirmation.provider_payment_charge_id
        and payment.provider_payment_charge_id != confirmation.provider_payment_charge_id
    ):
        return False
    return True


def _required_positive_int(value: int | str | None, reason_code: str) -> int:
    if value is None:
        raise PaymentConfigurationError(reason_code)
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise PaymentConfigurationError(reason_code) from exc
    if parsed <= 0:
        raise PaymentConfigurationError(reason_code)
    return parsed


def _as_aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
