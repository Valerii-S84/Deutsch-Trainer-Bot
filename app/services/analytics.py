from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import logging
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import and_, func, or_, select

from app.db.models import (
    AnalyticsEvent,
    ApiErrorLog,
    Payment,
    QuizSession,
    Subscription,
    User,
    UserAnswer,
)
from app.repositories.analytics_events import AnalyticsEventRepository

BERLIN_TZ = ZoneInfo("Europe/Berlin")
RETENTION_ACTIVITY_EVENTS = {
    "training_started",
    "question_answered",
    "training_completed",
    "progress_opened",
    "mistakes_opened",
    "mistakes_repeated",
}

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RateMetric:
    numerator: int
    denominator: int
    rate: float | None


@dataclass(frozen=True)
class DailyAdminMetrics:
    total_users: int
    new_users_today: int
    active_users_today: int
    training_sessions_today: int
    answers_today: int
    session_completion_rate_today: RateMetric
    progress_opened_today: int
    mistakes_repeated_today: int
    active_subscriptions: int
    payment_errors_today: int
    api_errors_today: int


@dataclass(frozen=True)
class ConversionMetrics:
    paywall_ctr_today: RateMetric
    payment_success_rate_today: RateMetric
    free_to_plus_today: int
    plus_to_pro_today: int
    subscription_expired_today: int
    expiration_recovery_rate_30d: RateMetric


@dataclass(frozen=True)
class RetentionMetrics:
    day_1: RateMetric
    day_7: RateMetric
    day_30: RateMetric


@dataclass(frozen=True)
class AdminMetricsSnapshot:
    generated_at: datetime
    daily: DailyAdminMetrics
    conversion: ConversionMetrics
    retention: RetentionMetrics


class AnalyticsTracker:
    """Best-effort analytics writer that never blocks product flow."""

    def __init__(self, repository: AnalyticsEventRepository | None = None) -> None:
        self._repository = repository or AnalyticsEventRepository()

    async def record(
        self,
        db,
        *,
        event_name: str,
        user_id: int | None,
        session_id: int | None = None,
        event_metadata: dict[str, Any] | None = None,
        source: str = "bot",
    ) -> AnalyticsEvent | None:
        try:
            return await self._repository.record(
                db,
                event_name=event_name,
                user_id=user_id,
                session_id=session_id,
                event_metadata=event_metadata,
                source=source,
            )
        except Exception:
            logger.warning(
                "analytics_write_failed event_name=%s source=%s",
                event_name,
                source,
                exc_info=True,
            )
            return None


class AnalyticsMetricsService:
    """Admin-facing product, learning, monetization and operations metrics."""

    async def get_admin_metrics(self, db, *, now: datetime | None = None) -> AdminMetricsSnapshot:
        generated_at = _as_aware_utc(now or datetime.now(UTC))
        day_start, day_end = _berlin_day_bounds(generated_at)
        daily = await self._daily_metrics(db, now=generated_at, day_start=day_start, day_end=day_end)
        conversion = await self._conversion_metrics(db, now=generated_at, day_start=day_start, day_end=day_end)
        retention = RetentionMetrics(
            day_1=await self._retention_metric(db, now=generated_at, days=1),
            day_7=await self._retention_metric(db, now=generated_at, days=7),
            day_30=await self._retention_metric(db, now=generated_at, days=30),
        )
        return AdminMetricsSnapshot(generated_at=generated_at, daily=daily, conversion=conversion, retention=retention)

    async def _daily_metrics(
        self,
        db,
        *,
        now: datetime,
        day_start: datetime,
        day_end: datetime,
    ) -> DailyAdminMetrics:
        started_sessions = await _count_rows(
            db,
            QuizSession.id,
            _between(QuizSession.started_at, day_start, day_end),
        )
        completed_sessions = await _count_rows(
            db,
            QuizSession.id,
            _between(QuizSession.started_at, day_start, day_end),
            QuizSession.status == "completed",
        )
        return DailyAdminMetrics(
            total_users=await _count_rows(db, User.id),
            new_users_today=await _count_rows(db, User.id, _between(User.created_at, day_start, day_end)),
            active_users_today=await _active_users_today(db, day_start=day_start, day_end=day_end),
            training_sessions_today=started_sessions,
            answers_today=await _count_rows(db, UserAnswer.id, _between(UserAnswer.answered_at, day_start, day_end)),
            session_completion_rate_today=_rate(completed_sessions, started_sessions),
            progress_opened_today=await _count_events(db, "progress_opened", day_start, day_end),
            mistakes_repeated_today=await _count_events(db, "mistakes_repeated", day_start, day_end),
            active_subscriptions=await _active_subscription_count(db, now=now),
            payment_errors_today=await _count_rows(db, Payment.id, _between(Payment.failed_at, day_start, day_end)),
            api_errors_today=await _count_rows(db, ApiErrorLog.id, _between(ApiErrorLog.occurred_at, day_start, day_end)),
        )

    async def _conversion_metrics(
        self,
        db,
        *,
        now: datetime,
        day_start: datetime,
        day_end: datetime,
    ) -> ConversionMetrics:
        paywall_shown = await _count_events(db, "paywall_shown", day_start, day_end)
        paywall_clicked = await _count_events(db, "paywall_clicked", day_start, day_end)
        payment_started = await _count_events(db, "payment_started", day_start, day_end)
        payment_succeeded = await _count_events(db, "payment_succeeded", day_start, day_end)
        return ConversionMetrics(
            paywall_ctr_today=_rate(paywall_clicked, paywall_shown),
            payment_success_rate_today=_rate(payment_succeeded, payment_started),
            free_to_plus_today=await _subscriptions_started(db, plan="plus", day_start=day_start, day_end=day_end),
            plus_to_pro_today=await _subscriptions_started(db, plan="pro", day_start=day_start, day_end=day_end),
            subscription_expired_today=await _expired_subscriptions(db, day_start=day_start, day_end=day_end),
            expiration_recovery_rate_30d=await self._expiration_recovery_rate(db, now=now),
        )

    async def _retention_metric(self, db, *, now: datetime, days: int) -> RateMetric:
        anchor_rows = await db.execute(select(User.id, User.created_at))
        result_rows = await db.execute(
            select(AnalyticsEvent.user_id, func.min(AnalyticsEvent.event_time))
            .where(AnalyticsEvent.event_name == "result_shown", AnalyticsEvent.user_id.is_not(None))
            .group_by(AnalyticsEvent.user_id),
        )
        result_by_user = {int(user_id): event_time for user_id, event_time in result_rows.all()}
        due_user_ids = _retention_due_users(anchor_rows.all(), result_by_user, now=now, days=days)
        if not due_user_ids:
            return _rate(0, 0)

        active_users = await _active_users_in_local_day(
            db,
            due_user_ids=due_user_ids,
            target_date=_berlin_date(now),
        )
        return _rate(len(active_users), len(due_user_ids))

    async def _expiration_recovery_rate(self, db, *, now: datetime) -> RateMetric:
        window_start = now - timedelta(days=30)
        expired_rows = await db.execute(
            select(Subscription.user_id, Subscription.expires_at)
            .where(
                Subscription.expires_at.is_not(None),
                Subscription.expires_at >= window_start,
                Subscription.expires_at < now,
            ),
        )
        expired = [(int(user_id), _as_aware_utc(expires_at)) for user_id, expires_at in expired_rows.all()]
        if not expired:
            return _rate(0, 0)

        start_rows = await db.execute(
            select(Subscription.user_id, Subscription.started_at)
            .where(
                Subscription.started_at.is_not(None),
                Subscription.started_at >= window_start,
                Subscription.started_at <= now,
                Subscription.status == "active",
            ),
        )
        starts = [(int(user_id), _as_aware_utc(started_at)) for user_id, started_at in start_rows.all()]
        recovered = _recovered_expired_users(expired, starts)
        expired_user_ids = {user_id for user_id, _ in expired}
        return _rate(len(recovered), len(expired_user_ids))


def format_admin_metrics(snapshot: AdminMetricsSnapshot) -> str:
    daily = snapshot.daily
    conversion = snapshot.conversion
    retention = snapshot.retention
    return "\n".join(
        [
            "Admin-Metriken",
            f"Stand: {snapshot.generated_at.astimezone(BERLIN_TZ).strftime('%d.%m.%Y %H:%M')}",
            "",
            f"Nutzer gesamt: {daily.total_users}",
            f"Neue Nutzer heute: {daily.new_users_today}",
            f"Aktive Nutzer heute: {daily.active_users_today}",
            f"Trainings heute: {daily.training_sessions_today}",
            f"Antworten heute: {daily.answers_today}",
            f"Abschlussrate der Übungen heute: {_format_rate(daily.session_completion_rate_today)}",
            f"Fortschritt geöffnet heute: {daily.progress_opened_today}",
            f"Fehler wiederholt heute: {daily.mistakes_repeated_today}",
            f"Aktive Abos: {daily.active_subscriptions}",
            f"Zahlungsfehler heute: {daily.payment_errors_today}",
            f"API-Fehler heute: {daily.api_errors_today}",
            "",
            f"Abo-Hinweis-Klickrate heute: {_format_rate(conversion.paywall_ctr_today)}",
            f"Zahlungserfolg heute: {_format_rate(conversion.payment_success_rate_today)}",
            f"Kostenlos zu Plus heute: {conversion.free_to_plus_today}",
            f"Plus zu Pro heute: {conversion.plus_to_pro_today}",
            f"Abos abgelaufen heute: {conversion.subscription_expired_today}",
            f"Reaktivierung nach Ablauf in 30 Tagen: {_format_rate(conversion.expiration_recovery_rate_30d)}",
            "",
            f"Nutzerbindung D1: {_format_rate(retention.day_1)}",
            f"Nutzerbindung D7: {_format_rate(retention.day_7)}",
            f"Nutzerbindung D30: {_format_rate(retention.day_30)}",
        ],
    )


async def _count_rows(db, column, *conditions) -> int:
    query = select(func.count(column))
    if conditions:
        query = query.where(*conditions)
    value = await db.scalar(query)
    return int(value or 0)


async def _count_events(db, event_name: str, day_start: datetime, day_end: datetime) -> int:
    return await _count_rows(
        db,
        AnalyticsEvent.id,
        AnalyticsEvent.event_name == event_name,
        _between(AnalyticsEvent.event_time, day_start, day_end),
    )


async def _active_users_today(db, *, day_start: datetime, day_end: datetime) -> int:
    value = await db.scalar(
        select(func.count(func.distinct(AnalyticsEvent.user_id))).where(
            AnalyticsEvent.user_id.is_not(None),
            AnalyticsEvent.event_name.in_(RETENTION_ACTIVITY_EVENTS),
            _between(AnalyticsEvent.event_time, day_start, day_end),
        ),
    )
    return int(value or 0)


async def _active_subscription_count(db, *, now: datetime) -> int:
    return await _count_rows(
        db,
        Subscription.id,
        Subscription.status == "active",
        or_(Subscription.expires_at.is_(None), Subscription.expires_at > now),
    )


async def _subscriptions_started(db, *, plan: str, day_start: datetime, day_end: datetime) -> int:
    return await _count_rows(
        db,
        Subscription.id,
        Subscription.plan == plan,
        _between(Subscription.started_at, day_start, day_end),
    )


async def _expired_subscriptions(db, *, day_start: datetime, day_end: datetime) -> int:
    return await _count_rows(
        db,
        Subscription.id,
        Subscription.expires_at.is_not(None),
        _between(Subscription.expires_at, day_start, day_end),
    )


async def _active_users_in_local_day(db, *, due_user_ids: set[int], target_date) -> set[int]:
    day_start = datetime(target_date.year, target_date.month, target_date.day, tzinfo=BERLIN_TZ).astimezone(UTC)
    day_end = day_start + timedelta(days=1)
    rows = await db.execute(
        select(AnalyticsEvent.user_id)
        .where(
            AnalyticsEvent.user_id.in_(due_user_ids),
            AnalyticsEvent.event_name.in_(RETENTION_ACTIVITY_EVENTS),
            _between(AnalyticsEvent.event_time, day_start, day_end),
        )
        .distinct(),
    )
    return {int(user_id) for user_id, in rows.all()}


def _retention_due_users(
    user_rows: list[tuple[int, datetime]],
    result_by_user: dict[int, datetime],
    *,
    now: datetime,
    days: int,
) -> set[int]:
    target_date = _berlin_date(now)
    due_user_ids: set[int] = set()
    for user_id, created_at in user_rows:
        anchor = result_by_user.get(int(user_id)) or created_at
        if _berlin_date(_as_aware_utc(anchor) + timedelta(days=days)) == target_date:
            due_user_ids.add(int(user_id))
    return due_user_ids


def _recovered_expired_users(
    expired: list[tuple[int, datetime]],
    starts: list[tuple[int, datetime]],
) -> set[int]:
    recovered: set[int] = set()
    for user_id, expires_at in expired:
        if any(start_user_id == user_id and started_at > expires_at for start_user_id, started_at in starts):
            recovered.add(user_id)
    return recovered


def _between(column, start: datetime, end: datetime):
    return and_(column.is_not(None), column >= start, column < end)


def _berlin_day_bounds(now: datetime) -> tuple[datetime, datetime]:
    local = now.astimezone(BERLIN_TZ)
    start_local = datetime(local.year, local.month, local.day, tzinfo=BERLIN_TZ)
    end_local = start_local + timedelta(days=1)
    return start_local.astimezone(UTC), end_local.astimezone(UTC)


def _berlin_date(value: datetime):
    return _as_aware_utc(value).astimezone(BERLIN_TZ).date()


def _as_aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _rate(numerator: int, denominator: int) -> RateMetric:
    rate = None if denominator == 0 else round(numerator / denominator, 4)
    return RateMetric(numerator=numerator, denominator=denominator, rate=rate)


def _format_rate(metric: RateMetric) -> str:
    if metric.rate is None:
        return "n/a"
    return f"{metric.rate * 100:.1f}% ({metric.numerator}/{metric.denominator})"
