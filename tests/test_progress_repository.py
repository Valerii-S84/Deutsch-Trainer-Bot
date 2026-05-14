from __future__ import annotations

from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.base import Base
from app.db.models import Progress, User
from app.repositories.progress import ProgressRepository


@pytest_asyncio.fixture
async def db_session() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)

    async with engine.begin() as connection:
        await connection.run_sync(
            Base.metadata.create_all,
            tables=[User.__table__, Progress.__table__],
        )

    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with session_factory() as session:
        yield session

    await engine.dispose()


@pytest_asyncio.fixture
async def sample_user(db_session: AsyncSession) -> User:
    user = User(id=1, telegram_user_id=1001)
    db_session.add(user)
    await db_session.flush()
    return user


@pytest.mark.asyncio
async def test_get_or_create_creates_progress_row(db_session: AsyncSession, sample_user: User) -> None:
    repository = ProgressRepository()
    progress = await repository.get_or_create(
        db_session,
        user_id=sample_user.id,
        level="A1",
        theme="Alltag",
    )

    assert progress.user_id == sample_user.id
    assert progress.level == "A1"
    assert progress.theme == "Alltag"
    assert progress.total_answered == 0
    assert progress.total_correct == 0
    assert progress.accuracy == Decimal("0.00")


@pytest.mark.asyncio
async def test_update_totals_updates_counts_and_accuracy(db_session: AsyncSession, sample_user: User) -> None:
    repository = ProgressRepository()
    progress = Progress(
        id=1,
        user_id=sample_user.id,
        level="A1",
        theme="Alltag",
        total_answered=0,
        total_correct=0,
        accuracy=Decimal("0.00"),
    )
    db_session.add(progress)

    updated = await repository.update_totals(db_session, progress, answered_delta=3, correct_delta=2)
    assert updated.total_answered == 3
    assert updated.total_correct == 2
    assert updated.accuracy == Decimal("66.67")


@pytest.mark.asyncio
async def test_update_totals_prevents_negative_values(db_session: AsyncSession, sample_user: User) -> None:
    repository = ProgressRepository()
    progress = Progress(
        id=1,
        user_id=sample_user.id,
        level="A1",
        theme="Alltag",
        total_answered=1,
        total_correct=1,
        accuracy=Decimal("100.00"),
    )
    db_session.add(progress)

    updated = await repository.update_totals(db_session, progress, answered_delta=-3, correct_delta=-5)
    assert updated.total_answered == 1
    assert updated.total_correct == 1
    assert updated.accuracy == Decimal("100.00")


@pytest.mark.asyncio
async def test_user_and_level_theme_summary_queries(db_session: AsyncSession, sample_user: User) -> None:
    repository = ProgressRepository()
    second_user = User(id=2, telegram_user_id=2002)
    db_session.add(second_user)
    await db_session.flush()

    await repository.create(db_session, user_id=sample_user.id, level="A1", theme="Alltag")
    await repository.create(db_session, user_id=sample_user.id, level="A1", theme="Beruf")
    await repository.create(db_session, user_id=sample_user.id, level="B1", theme="Alltag")
    await repository.create(db_session, user_id=second_user.id, level="A1", theme="Alltag")

    user_summary = await repository.get_user_summary(db_session, user_id=sample_user.id)
    assert len(user_summary) == 3
    assert {entry.theme for entry in user_summary} >= {"Alltag", "Beruf"}

    level_summary = await repository.get_level_theme_summary(
        db_session,
        user_id=sample_user.id,
        level="A1",
    )
    assert len(level_summary) == 2
    assert {entry.theme for entry in level_summary} == {"Alltag", "Beruf"}

    theme_summary = await repository.get_level_theme_summary(
        db_session,
        user_id=sample_user.id,
        theme="Alltag",
    )
    assert len(theme_summary) == 2
    assert {entry.level for entry in theme_summary} == {"A1", "B1"}
