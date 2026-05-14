from __future__ import annotations

from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.base import Base
from app.db.models import Progress, User
from app.services.progress import ProgressService
from app.repositories.users import UserRepository


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


class _StaticUserRepository(UserRepository):
    def __init__(self) -> None:
        self._next_id = 1
        self._users: dict[int, User] = {}

    async def get_by_telegram_id(self, db: AsyncSession, telegram_user_id: int) -> User | None:
        return self._users.get(telegram_user_id)

    async def create_if_missing(self, db: AsyncSession, telegram_user_id: int) -> User:
        existing = await self.get_by_telegram_id(db, telegram_user_id)
        if existing is not None:
            return existing

        user = User(id=self._next_id, telegram_user_id=telegram_user_id)
        self._next_id += 1
        self._users[telegram_user_id] = user
        db.add(user)
        return user


class _FakeProgressHistoryRepository:
    def __init__(self) -> None:
        self.records: list[dict[str, object]] = []

    def snapshot_scores(self, progress: Progress) -> dict[str, object]:
        return {
            "total_answered": int(progress.total_answered or 0),
            "total_correct": int(progress.total_correct or 0),
            "accuracy": float(progress.accuracy or 0),
            "topic_status": progress.topic_status,
        }

    async def record_answer_change(self, db, *, progress: Progress, **kwargs: object) -> None:
        self.records.append(
            {
                "progress_id": progress.id,
                "total_answered": progress.total_answered,
                "total_correct": progress.total_correct,
                **kwargs,
            },
        )


def _progress_service(user_repo: _StaticUserRepository) -> ProgressService:
    return ProgressService(
        user_repo=user_repo,
        progress_history_repo=_FakeProgressHistoryRepository(),
    )


@pytest.mark.asyncio
async def test_record_answer_result_creates_progress_for_first_answer(db_session: AsyncSession) -> None:
    user_repo = _StaticUserRepository()
    history_repo = _FakeProgressHistoryRepository()
    service = ProgressService(user_repo=user_repo, progress_history_repo=history_repo)
    user = await user_repo.create_if_missing(db_session, telegram_user_id=1111)

    progress = await service.record_answer_result(
        db_session,
        user.telegram_user_id,
        level="A1",
        theme="Alltag",
        is_correct=True,
        is_duplicate=False,
    )

    assert progress.user_id == user.id
    assert progress.total_answered == 1
    assert progress.total_correct == 1
    assert progress.accuracy == Decimal("100.00")
    assert len(history_repo.records) == 1
    assert history_repo.records[0]["reason_code"] == "answer_accepted"


@pytest.mark.asyncio
async def test_record_answer_result_updates_total_answered(db_session: AsyncSession) -> None:
    user_repo = _StaticUserRepository()
    service = _progress_service(user_repo)
    user = await user_repo.create_if_missing(db_session, telegram_user_id=1112)

    first = await service.record_answer_result(
        db_session,
        user.telegram_user_id,
        level="A1",
        theme="Alltag",
        is_correct=True,
        is_duplicate=False,
    )
    first_total_answered = first.total_answered
    second = await service.record_answer_result(
        db_session,
        user.telegram_user_id,
        level="A1",
        theme="Alltag",
        is_correct=False,
        is_duplicate=False,
    )

    assert first_total_answered == 1
    assert second.total_answered == 2


@pytest.mark.asyncio
async def test_record_answer_result_updates_correct_only_for_correct_answers(db_session: AsyncSession) -> None:
    user_repo = _StaticUserRepository()
    service = _progress_service(user_repo)
    user = await user_repo.create_if_missing(db_session, telegram_user_id=1113)

    await service.record_answer_result(
        db_session,
        user.telegram_user_id,
        level="A1",
        theme="Alltag",
        is_correct=False,
        is_duplicate=False,
    )
    progress = await service.record_answer_result(
        db_session,
        user.telegram_user_id,
        level="A1",
        theme="Alltag",
        is_correct=True,
        is_duplicate=False,
    )

    assert progress.total_answered == 2
    assert progress.total_correct == 1


@pytest.mark.asyncio
async def test_record_answer_result_calculates_accuracy(db_session: AsyncSession) -> None:
    user_repo = _StaticUserRepository()
    service = _progress_service(user_repo)
    user = await user_repo.create_if_missing(db_session, telegram_user_id=1114)

    await service.record_answer_result(
        db_session,
        user.telegram_user_id,
        level="A1",
        theme="Alltag",
        is_correct=True,
        is_duplicate=False,
    )
    await service.record_answer_result(
        db_session,
        user.telegram_user_id,
        level="A1",
        theme="Alltag",
        is_correct=False,
        is_duplicate=False,
    )
    progress = await service.record_answer_result(
        db_session,
        user.telegram_user_id,
        level="A1",
        theme="Alltag",
        is_correct=True,
        is_duplicate=False,
    )

    assert progress.total_answered == 3
    assert progress.total_correct == 2
    assert progress.accuracy == Decimal("66.67")


@pytest.mark.asyncio
async def test_record_answer_result_does_not_change_progress_for_duplicate(db_session: AsyncSession) -> None:
    user_repo = _StaticUserRepository()
    service = _progress_service(user_repo)
    user = await user_repo.create_if_missing(db_session, telegram_user_id=1115)

    first = await service.record_answer_result(
        db_session,
        user.telegram_user_id,
        level="A1",
        theme="Alltag",
        is_correct=True,
        is_duplicate=False,
    )
    duplicate = await service.record_answer_result(
        db_session,
        user.telegram_user_id,
        level="A1",
        theme="Alltag",
        is_correct=True,
        is_duplicate=True,
    )

    assert first.total_answered == 1
    assert duplicate.total_answered == 1
    assert duplicate.total_correct == 1
