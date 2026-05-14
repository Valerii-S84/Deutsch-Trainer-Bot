from __future__ import annotations

from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.base import Base
from app.db.models import Mistake, MistakeStatus, User
from app.repositories.mistakes import MistakeRepository


@pytest_asyncio.fixture
async def db_session() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)

    async with engine.begin() as connection:
        await connection.run_sync(
            Base.metadata.create_all,
            tables=[User.__table__, Mistake.__table__],
        )

    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with session_factory() as session:
        yield session

    await engine.dispose()


@pytest_asyncio.fixture
async def sample_user(db_session: AsyncSession) -> User:
    user = User(id=1, telegram_user_id=1111)
    db_session.add(user)
    await db_session.flush()
    return user


@pytest.mark.asyncio
async def test_create_and_find_active_mistake(db_session: AsyncSession, sample_user: User) -> None:
    repository = MistakeRepository()

    created = await repository.create(
        db_session,
        user_id=sample_user.id,
        external_quiz_id="quiz-1",
        level="A1",
        theme="Alltag",
        wrong_answer="a2",
        correct_answer="a1",
    )

    by_id = await repository.find_active_by_user_and_external_quiz_id(
        db_session,
        user_id=sample_user.id,
        external_quiz_id="quiz-1",
    )

    assert by_id is not None
    assert by_id.id == created.id
    assert by_id.external_quiz_id == "quiz-1"
    assert by_id.status == MistakeStatus.new
    assert by_id.mistake_count == 1


@pytest.mark.asyncio
async def test_increment_wrong_increases_count_and_marks_repeated(db_session: AsyncSession, sample_user: User) -> None:
    repository = MistakeRepository()
    mistake = Mistake(
        id=1,
        user_id=sample_user.id,
        external_quiz_id="quiz-2",
        level="A1",
        theme="Beruf",
        wrong_answer="a2",
        correct_answer="a1",
        mistake_count=2,
        status=MistakeStatus.new,
        last_seen_at=datetime.now(UTC),
    )
    db_session.add(mistake)

    updated = await repository.increment_wrong(
        db_session,
        mistake,
        wrong_answer="a3",
        correct_answer="a1",
    )

    assert updated.mistake_count == 3
    assert updated.status == MistakeStatus.repeated
    assert updated.wrong_answer == "a3"
    assert updated.resolved_at is None


@pytest.mark.asyncio
async def test_list_active_for_user_ignores_resolved(db_session: AsyncSession, sample_user: User) -> None:
    repository = MistakeRepository()

    await repository.create(
        db_session,
        user_id=sample_user.id,
        external_quiz_id="quiz-3",
        level="A1",
        theme="Alltag",
        wrong_answer="a2",
        correct_answer="a1",
    )
    resolved = await repository.create(
        db_session,
        user_id=sample_user.id,
        external_quiz_id="quiz-4",
        level="B1",
        theme="Beruf",
        wrong_answer="a2",
        correct_answer="a1",
    )
    resolved.status = MistakeStatus.resolved
    resolved.resolved_at = datetime.now(UTC)

    active = await repository.list_active_for_user(db_session, user_id=sample_user.id)

    assert len(active) == 1
    assert active[0].external_quiz_id == "quiz-3"


@pytest.mark.asyncio
async def test_get_weak_area_summary_counts_by_level_theme(db_session: AsyncSession, sample_user: User) -> None:
    repository = MistakeRepository()

    active_a1 = await repository.create(
        db_session,
        user_id=sample_user.id,
        external_quiz_id="quiz-5",
        level="A1",
        theme="Alltag",
        wrong_answer="a2",
        correct_answer="a1",
    )
    await repository.increment_wrong(
        db_session,
        active_a1,
        wrong_answer="a3",
        correct_answer="a1",
    )

    await repository.create(
        db_session,
        user_id=sample_user.id,
        external_quiz_id="quiz-6",
        level="B1",
        theme="Alltag",
        wrong_answer="b2",
        correct_answer="b1",
    )

    summary = await repository.get_weak_area_summary(db_session, user_id=sample_user.id)
    assert len(summary) == 2
    assert summary[0]["level"] == "A1"
    assert summary[0]["theme"] == "Alltag"
    assert summary[0]["mistake_count"] == 2
    assert summary[1]["level"] == "B1"
    assert summary[1]["theme"] == "Alltag"
    assert summary[1]["mistake_count"] == 1
