from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final

from app.config import Settings, get_settings
from app.db.models import DailyLimit, Subscription
from app.repositories.analytics_events import AnalyticsEventRepository
from app.repositories.daily_limits import DailyLimitRepository
from app.repositories.subscriptions import SubscriptionRepository
from app.repositories.users import UserRepository

PLAN_FREE: Final = "free"
PLAN_PLUS: Final = "plus"
PLAN_PRO: Final = "pro"

FEATURE_SELECT_LEVEL: Final = "select_level"
FEATURE_SELECT_THEME: Final = "select_theme"
FEATURE_BASIC_RESULT: Final = "basic_result"
FEATURE_SHORT_PROGRESS: Final = "short_progress"
FEATURE_FULL_PROGRESS_MAP: Final = "full_progress_map"
FEATURE_TOPIC_PROGRESS_DETAIL: Final = "topic_progress_detail"
FEATURE_MISTAKE_JOURNAL: Final = "mistake_journal"
FEATURE_MISTAKE_REPEAT: Final = "mistake_repeat"
FEATURE_DAILY_RECOMMENDATION: Final = "daily_recommendation"
FEATURE_ADVANCED_STATISTICS: Final = "advanced_statistics"
FEATURE_PERSONAL_LEARNING_PLAN: Final = "personal_learning_plan"

PLAN_RANK: Final[dict[str, int]] = {
    PLAN_FREE: 0,
    PLAN_PLUS: 1,
    PLAN_PRO: 2,
}

FEATURE_MIN_PLAN: Final[dict[str, str]] = {
    FEATURE_SELECT_LEVEL: PLAN_FREE,
    FEATURE_SELECT_THEME: PLAN_FREE,
    FEATURE_BASIC_RESULT: PLAN_FREE,
    FEATURE_SHORT_PROGRESS: PLAN_FREE,
    FEATURE_FULL_PROGRESS_MAP: PLAN_PLUS,
    FEATURE_TOPIC_PROGRESS_DETAIL: PLAN_PLUS,
    FEATURE_MISTAKE_JOURNAL: PLAN_PLUS,
    FEATURE_MISTAKE_REPEAT: PLAN_PLUS,
    FEATURE_DAILY_RECOMMENDATION: PLAN_PLUS,
    FEATURE_ADVANCED_STATISTICS: PLAN_PRO,
    FEATURE_PERSONAL_LEARNING_PLAN: PLAN_PRO,
}


@dataclass(frozen=True)
class EntitlementDecision:
    allowed: bool
    feature: str
    user_plan: str
    required_plan: str
    reason_code: str


@dataclass(frozen=True)
class AccessState:
    user_id: int
    plan: str
    subscription: Subscription | None


@dataclass(frozen=True)
class SubscriptionStatusState:
    user_id: int
    access_plan: str
    status_plan: str
    status: str
    expires_at: datetime | None
    subscription: Subscription | None


@dataclass(frozen=True)
class DailyLimitState:
    plan: str
    question_limit: int
    questions_used: int
    remaining: int
    reset_at: datetime
    daily_limit: DailyLimit


class EntitlementDeniedError(Exception):
    """Raised when a user lacks the required feature entitlement."""

    def __init__(self, decision: EntitlementDecision) -> None:
        super().__init__(decision.reason_code)
        self.decision = decision


class DailyLimitExceededError(Exception):
    """Raised when the current plan daily question limit is reached."""

    def __init__(self, state: DailyLimitState) -> None:
        super().__init__("daily_limit_reached")
        self.state = state


class EntitlementService:
    """Plan, subscription and daily-limit access checks."""

    def __init__(
        self,
        *,
        user_repo: UserRepository | None = None,
        subscription_repo: SubscriptionRepository | None = None,
        daily_limit_repo: DailyLimitRepository | None = None,
        analytics_repo: AnalyticsEventRepository | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._user_repo = user_repo or UserRepository()
        self._subscription_repo = subscription_repo or SubscriptionRepository()
        self._daily_limit_repo = daily_limit_repo or DailyLimitRepository()
        self._analytics_repo = analytics_repo or AnalyticsEventRepository()
        self._settings = settings or get_settings()

    async def get_access_state(self, db, telegram_user_id: int, *, now: datetime | None = None) -> AccessState:
        user = await self._user_repo.create_if_missing(db, telegram_user_id)
        if getattr(user, "id", None) is None and hasattr(db, "flush"):
            await db.flush()
        subscription = await self._subscription_repo.get_effective_paid_subscription(
            db,
            user_id=user.id,
            now=now or datetime.now(UTC),
        )
        plan = subscription.plan if subscription is not None else PLAN_FREE
        return AccessState(user_id=user.id, plan=plan, subscription=subscription)

    async def get_subscription_status_state(
        self,
        db,
        telegram_user_id: int,
        *,
        now: datetime | None = None,
    ) -> SubscriptionStatusState:
        user = await self._user_repo.create_if_missing(db, telegram_user_id)
        if getattr(user, "id", None) is None and hasattr(db, "flush"):
            await db.flush()

        current_time = _as_aware_utc(now or datetime.now(UTC))
        subscription = await self._subscription_repo.get_effective_paid_subscription(
            db,
            user_id=user.id,
            now=current_time,
        )
        if subscription is not None:
            return SubscriptionStatusState(
                user_id=user.id,
                access_plan=subscription.plan,
                status_plan=subscription.plan,
                status="active",
                expires_at=_as_aware_utc(subscription.expires_at),
                subscription=subscription,
            )

        latest_subscription = await self._subscription_repo.get_latest_for_user(db, user_id=user.id)
        if latest_subscription is None:
            return SubscriptionStatusState(
                user_id=user.id,
                access_plan=PLAN_FREE,
                status_plan=PLAN_FREE,
                status="inactive",
                expires_at=None,
                subscription=None,
            )

        return SubscriptionStatusState(
            user_id=user.id,
            access_plan=PLAN_FREE,
            status_plan=latest_subscription.plan,
            status=_subscription_status(latest_subscription, current_time),
            expires_at=_as_aware_utc(latest_subscription.expires_at),
            subscription=latest_subscription,
        )

    async def check_entitlement(
        self,
        db,
        telegram_user_id: int,
        *,
        feature: str,
        now: datetime | None = None,
    ) -> EntitlementDecision:
        access_state = await self.get_access_state(db, telegram_user_id, now=now)
        required_plan = FEATURE_MIN_PLAN[feature]
        allowed = plan_includes(access_state.plan, required_plan)
        reason_code = "allowed" if allowed else "entitlement_required"
        return EntitlementDecision(
            allowed=allowed,
            feature=feature,
            user_plan=access_state.plan,
            required_plan=required_plan,
            reason_code=reason_code,
        )

    async def ensure_entitlement(
        self,
        db,
        telegram_user_id: int,
        *,
        feature: str,
        now: datetime | None = None,
    ) -> EntitlementDecision:
        decision = await self.check_entitlement(db, telegram_user_id, feature=feature, now=now)
        if not decision.allowed:
            raise EntitlementDeniedError(decision)
        return decision

    async def get_daily_limit_state(
        self,
        db,
        telegram_user_id: int,
        *,
        now: datetime | None = None,
    ) -> DailyLimitState:
        access_state = await self.get_access_state(db, telegram_user_id, now=now)
        question_limit = self._daily_question_limit(access_state.plan)
        daily_limit = await self._daily_limit_repo.get_or_create_for_today(
            db,
            user_id=access_state.user_id,
            plan=access_state.plan,
            question_limit=question_limit,
            now=now,
        )
        return _daily_limit_state(access_state.plan, daily_limit)

    async def ensure_daily_question_available(
        self,
        db,
        telegram_user_id: int,
        *,
        session_id: int | None = None,
        level: str | None = None,
        theme: str | None = None,
        now: datetime | None = None,
    ) -> DailyLimitState:
        state = await self.get_daily_limit_state(db, telegram_user_id, now=now)
        if state.remaining > 0:
            return state
        await self._record_limit_hit(
            db,
            state=state,
            session_id=session_id,
            level=level,
            theme=theme,
        )
        raise DailyLimitExceededError(state)

    async def charge_daily_question(
        self,
        db,
        telegram_user_id: int,
        *,
        now: datetime | None = None,
    ) -> DailyLimitState:
        state = await self.get_daily_limit_state(db, telegram_user_id, now=now)
        if state.remaining <= 0:
            raise DailyLimitExceededError(state)
        daily_limit = await self._daily_limit_repo.charge_question(db, state.daily_limit)
        return _daily_limit_state(state.plan, daily_limit)

    def _daily_question_limit(self, plan: str) -> int:
        if plan == PLAN_PRO:
            return self._settings.pro_daily_question_limit
        if plan == PLAN_PLUS:
            return self._settings.plus_daily_question_limit
        return self._settings.free_daily_question_limit

    async def _record_limit_hit(
        self,
        db,
        *,
        state: DailyLimitState,
        session_id: int | None,
        level: str | None,
        theme: str | None,
    ) -> None:
        metadata = {
            "plan": state.plan,
            "question_limit": state.question_limit,
            "questions_used": state.questions_used,
            "level": level,
            "theme": theme,
        }
        for event_name in ("daily_limit_hit", "training_blocked_by_limit", "paywall_shown"):
            await self._analytics_repo.record(
                db,
                event_name=event_name,
                user_id=state.daily_limit.user_id,
                session_id=session_id,
                event_metadata={
                    **metadata,
                    "paywall_context": "daily_limit" if event_name == "paywall_shown" else None,
                    "trigger": "daily_limit_hit",
                    "plan_offered": PLAN_PLUS,
                    "user_plan": state.plan,
                },
                source="entitlements",
            )


def plan_includes(user_plan: str, required_plan: str) -> bool:
    return PLAN_RANK[user_plan] >= PLAN_RANK[required_plan]


def _subscription_status(subscription: Subscription, current_time: datetime) -> str:
    status = str(subscription.status or "inactive")
    expires_at = _as_aware_utc(subscription.expires_at)
    if status == "active" and expires_at is not None and expires_at <= _as_aware_utc(current_time):
        return "expired"
    if status == "active" and subscription.plan != PLAN_FREE:
        return "pending"
    if status in {"pending", "expired", "cancelled", "failed"}:
        return status
    return "inactive"


def _as_aware_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _daily_limit_state(plan: str, daily_limit: DailyLimit) -> DailyLimitState:
    remaining = max(0, int(daily_limit.question_limit or 0) - int(daily_limit.questions_used or 0))
    return DailyLimitState(
        plan=plan,
        question_limit=int(daily_limit.question_limit or 0),
        questions_used=int(daily_limit.questions_used or 0),
        remaining=remaining,
        reset_at=daily_limit.reset_at,
        daily_limit=daily_limit,
    )
