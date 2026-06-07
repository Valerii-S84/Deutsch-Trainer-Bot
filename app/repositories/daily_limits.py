from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import DailyLimit
from app.repositories.sqlite_compat import next_sqlite_id_if_needed

BERLIN_TZ = ZoneInfo("Europe/Berlin")


class DailyLimitRepository:
    """Persistence for Europe/Berlin daily question usage."""

    async def get_for_today(
        self,
        db: AsyncSession,
        *,
        user_id: int,
        plan: str,
        now: datetime | None = None,
    ) -> DailyLimit | None:
        limit_date, _ = _limit_window(now or datetime.now(UTC))
        query = select(DailyLimit).where(
            and_(
                DailyLimit.user_id == user_id,
                DailyLimit.plan == plan,
                DailyLimit.limit_date == limit_date,
            ),
        )
        return await db.scalar(query)

    async def get_or_create_for_today(
        self,
        db: AsyncSession,
        *,
        user_id: int,
        plan: str,
        question_limit: int,
        now: datetime | None = None,
    ) -> DailyLimit:
        current_time = now or datetime.now(UTC)
        limit_date, reset_at = _limit_window(current_time)
        existing = await self.get_for_today(db, user_id=user_id, plan=plan, now=current_time)
        if existing is not None:
            existing.question_limit = max(question_limit, int(existing.questions_used or 0))
            existing.reset_at = reset_at
            return existing

        daily_limit = DailyLimit(
            id=await next_sqlite_id_if_needed(db, DailyLimit),
            user_id=user_id,
            plan=plan,
            limit_date=limit_date,
            timezone="Europe/Berlin",
            question_limit=question_limit,
            questions_used=0,
            reset_at=reset_at,
        )
        db.add(daily_limit)
        return daily_limit

    async def charge_question(self, _db: AsyncSession, daily_limit: DailyLimit) -> DailyLimit:
        if daily_limit.questions_used >= daily_limit.question_limit:
            raise ValueError("Daily question limit is already reached")
        daily_limit.questions_used = int(daily_limit.questions_used or 0) + 1
        return daily_limit


def _limit_window(value: datetime):
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    local_now = value.astimezone(BERLIN_TZ)
    tomorrow = local_now.date() + timedelta(days=1)
    tomorrow_reset_at = datetime.combine(tomorrow, time.min, tzinfo=BERLIN_TZ)
    return local_now.date(), tomorrow_reset_at.astimezone(UTC)
