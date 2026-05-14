from __future__ import annotations

from datetime import UTC, datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import User


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

        user = User(telegram_user_id=telegram_user_id)
        db.add(user)
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
