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
    assert updated.successful_repeats_count == 0
    assert updated.successful_repeat_days_count == 0


@pytest.mark.asyncio
async def test_successful_repeat_once_marks_improved_not_resolved(
    db_session: AsyncSession,
    sample_user: User,
) -> None:
    repository = MistakeRepository()
    mistake = await repository.create(
        db_session,
        user_id=sample_user.id,
        external_quiz_id="quiz-repeat-1",
        level="A1",
        theme="Alltag",
        wrong_answer="a2",
        correct_answer="a1",
    )

    updated = await repository.record_successful_repeat(
        db_session,
        mistake,
        correct_answer="a1",
        answered_at=datetime(2026, 5, 14, 10, 0, tzinfo=UTC),
    )

    assert updated.status == MistakeStatus.improved
    assert updated.resolved_at is None
    assert updated.successful_repeats_count == 1
    assert updated.successful_repeat_days_count == 1


@pytest.mark.asyncio
async def test_successful_repeats_across_two_days_resolve(
    db_session: AsyncSession,
    sample_user: User,
) -> None:
    repository = MistakeRepository()
    mistake = await repository.create(
        db_session,
        user_id=sample_user.id,
        external_quiz_id="quiz-repeat-2",
        level="A1",
        theme="Alltag",
        wrong_answer="a2",
        correct_answer="a1",
    )

    await repository.record_successful_repeat(
        db_session,
        mistake,
        correct_answer="a1",
        answered_at=datetime(2026, 5, 14, 10, 0, tzinfo=UTC),
    )
    await repository.record_successful_repeat(
        db_session,
        mistake,
        correct_answer="a1",
        answered_at=datetime(2026, 5, 14, 11, 0, tzinfo=UTC),
    )
    resolved = await repository.record_successful_repeat(
        db_session,
        mistake,
        correct_answer="a1",
        answered_at=datetime(2026, 5, 15, 10, 0, tzinfo=UTC),
    )

    assert resolved.status == MistakeStatus.resolved
    assert resolved.resolved_at == datetime(2026, 5, 15, 10, 0, tzinfo=UTC)
    assert resolved.successful_repeats_count == 3
    assert resolved.successful_repeat_days_count == 2


@pytest.mark.asyncio
async def test_wrong_after_improved_resets_successful_repeats(
    db_session: AsyncSession,
    sample_user: User,
) -> None:
    repository = MistakeRepository()
    mistake = await repository.create(
        db_session,
        user_id=sample_user.id,
        external_quiz_id="quiz-repeat-3",
        level="A1",
        theme="Alltag",
        wrong_answer="a2",
        correct_answer="a1",
    )
    await repository.record_successful_repeat(
        db_session,
        mistake,
        correct_answer="a1",
        answered_at=datetime(2026, 5, 14, 10, 0, tzinfo=UTC),
    )

    repeated = await repository.increment_wrong(
        db_session,
        mistake,
        wrong_answer="a3",
        correct_answer="a1",
    )

    assert repeated.status == MistakeStatus.repeated
    assert repeated.successful_repeats_count == 0
    assert repeated.successful_repeat_days_count == 0
    assert repeated.last_successful_repeat_at is None


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
async def test_list_active_for_user_ignores_content_unavailable(
    db_session: AsyncSession,
    sample_user: User,
) -> None:
    repository = MistakeRepository()
    available = await repository.create(
        db_session,
        user_id=sample_user.id,
        external_quiz_id="quiz-available",
        level="A1",
        theme="Alltag",
        wrong_answer="a2",
        correct_answer="a1",
    )
    unavailable = await repository.create(
        db_session,
        user_id=sample_user.id,
        external_quiz_id="quiz-unavailable",
        level="A1",
        theme="Alltag",
        wrong_answer="a2",
        correct_answer="a1",
    )
    await repository.mark_content_unavailable(db_session, unavailable)

    active = await repository.list_active_for_user(db_session, user_id=sample_user.id)
    summary = await repository.get_weak_area_summary(db_session, user_id=sample_user.id)

    assert [item.external_quiz_id for item in active] == [available.external_quiz_id]
    assert summary[0]["mistake_count"] == 2


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
