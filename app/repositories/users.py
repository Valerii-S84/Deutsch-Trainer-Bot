from __future__ import annotations

from datetime import UTC, datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import User
from app.repositories.sqlite_compat import next_sqlite_id_if_needed


class UserRepository:
    """User data access helpers for training flow."""

    async def get_by_telegram_id(self, db: AsyncSession, telegram_user_id: int) -> Optional[User]:
        result = await db.scalar(
            select(User).where(User.telegram_user_id == telegram_user_id),
        )
        return result

    async def create_if_missing(self, db: AsyncSession, telegram_user_id: int) -> User:
        user = await self.get_by_telegram_id(db, telegram_user_id)
        if user is not None:
            return user

        user = User(id=await next_sqlite_id_if_needed(db, User), telegram_user_id=telegram_user_id)
        db.add(user)
        user.last_active_at = datetime.now(UTC)
        return user

    async def create_or_update_from_telegram(self, db: AsyncSession, telegram_user) -> User | None:
        telegram_user_id = getattr(telegram_user, "id", None)
        if telegram_user_id is None:
            return None

        user = await self.create_if_missing(db, int(telegram_user_id))
        user.username = getattr(telegram_user, "username", None)
        user.first_name = getattr(telegram_user, "first_name", None)
        user.language_code = getattr(telegram_user, "language_code", None)
        user.last_active_at = datetime.now(UTC)
        return user

    async def set_training_preferences(
        self,
        db: AsyncSession,
        telegram_user_id: int,
        *,
        level: str | None = None,
        theme: str | None = None,
    ) -> User:
        user = await self.create_if_missing(db, telegram_user_id)
        if level is not None:
            user.selected_level = level
        if theme is not None:
            user.selected_theme = theme
        user.last_active_at = datetime.now(UTC)
        return user
