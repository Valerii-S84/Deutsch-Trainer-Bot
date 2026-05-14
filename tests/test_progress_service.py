from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.base import Base
from app.db.models import Mistake, Progress, QuizSession, User, UserAnswer
from app.quiz_bank.schemas import QuizLevel, QuizLevelsResponse, QuizTheme, QuizThemesResponse
from app.services.progress import ProgressService
from app.repositories.users import UserRepository


@pytest_asyncio.fixture
async def db_session() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)

    async with engine.begin() as connection:
        await connection.run_sync(
            Base.metadata.create_all,
            tables=[
                User.__table__,
                QuizSession.__table__,
                UserAnswer.__table__,
                Progress.__table__,
                Mistake.__table__,
            ],
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


class _FakeQuizBankCatalog:
    async def get_levels(self) -> QuizLevelsResponse:
        return QuizLevelsResponse(
            levels=[QuizLevel(code="A1", display_name="A1", is_active=True)],
        )

    async def get_themes(self, *, level: str) -> QuizThemesResponse:
        return QuizThemesResponse(
            level=level,
            themes=[
                QuizTheme(theme="Alltag", theme_key="alltag", is_active=True, available_items_count=10),
                QuizTheme(theme="Artikel", theme_key="artikel", is_active=True, available_items_count=8),
            ],
        )


def _progress_service(user_repo: _StaticUserRepository) -> ProgressService:
    return ProgressService(
        user_repo=user_repo,
        progress_history_repo=_FakeProgressHistoryRepository(),
    )


@pytest.mark.asyncio
async def test_get_user_summary_includes_available_topics_without_answers(db_session: AsyncSession) -> None:
    user_repo = _StaticUserRepository()
    service = ProgressService(
        user_repo=user_repo,
        progress_history_repo=_FakeProgressHistoryRepository(),
        quiz_service=_FakeQuizBankCatalog(),
    )
    user = await user_repo.create_if_missing(db_session, telegram_user_id=1191)

    records = await service.get_user_summary(db_session, user.telegram_user_id)

    assert [(record.level, record.theme, record.total_answered) for record in records] == [
        ("A1", "Alltag", 0),
        ("A1", "Artikel", 0),
    ]
    assert records[0].available_items_count == 10
    assert records[0].coverage_status == "known"


@pytest.mark.asyncio
async def test_get_level_theme_summary_merges_catalog_counts_for_existing_rows(db_session: AsyncSession) -> None:
    user_repo = _StaticUserRepository()
    service = ProgressService(
        user_repo=user_repo,
        progress_history_repo=_FakeProgressHistoryRepository(),
        quiz_service=_FakeQuizBankCatalog(),
    )
    user = await user_repo.create_if_missing(db_session, telegram_user_id=1192)
    await service.record_answer_result(
        db_session,
        user.telegram_user_id,
        level="A1",
        theme="Alltag",
        is_correct=True,
        is_duplicate=False,
    )

    records = await service.get_level_theme_summary(db_session, user.telegram_user_id, level="A1")
    alltag = next(record for record in records if record.theme == "Alltag")
    artikel = next(record for record in records if record.theme == "Artikel")

    assert alltag.available_items_count == 10
    assert alltag.coverage_status == "known"
    assert artikel.total_answered == 0


@pytest.mark.asyncio
async def test_progress_summary_preserves_unknown_coverage_without_catalog(db_session: AsyncSession) -> None:
    user_repo = _StaticUserRepository()
    service = ProgressService(user_repo=user_repo, progress_history_repo=_FakeProgressHistoryRepository())
    user = await user_repo.create_if_missing(db_session, telegram_user_id=1193)
    progress = await service.record_answer_result(
        db_session,
        user.telegram_user_id,
        level="A1",
        theme="Alltag",
        is_correct=True,
        is_duplicate=False,
    )

    records = await service.get_user_summary(db_session, user.telegram_user_id)

    assert records == [progress]
    assert records[0].coverage_status == "unknown"


async def _add_session(db: AsyncSession, user: User, *, session_id: int) -> QuizSession:
    session = QuizSession(
        id=session_id,
        user_id=user.id,
        level="A1",
        theme="Alltag",
        status="active",
        total_questions=20,
        source="test",
    )
    db.add(session)
    await db.flush()
    return session


async def _add_answer(
    db: AsyncSession,
    *,
    answer_id: int,
    session_id: int,
    user: User,
    item_id: str,
    is_correct: bool,
    answered_at: datetime,
) -> UserAnswer:
    answer = UserAnswer(
        id=answer_id,
        session_id=session_id,
        user_id=user.id,
        external_quiz_id=item_id,
        level="A1",
        theme="Alltag",
        selected_answer="a1",
        correct_answer="a1" if is_correct else "a2",
        is_correct=is_correct,
        answered_at=answered_at,
    )
    db.add(answer)
    await db.flush()
    return answer


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


@pytest.mark.asyncio
async def test_record_answer_result_updates_coverage_from_unique_items(db_session: AsyncSession) -> None:
    user_repo = _StaticUserRepository()
    service = _progress_service(user_repo)
    user = await user_repo.create_if_missing(db_session, telegram_user_id=1116)
    await _add_session(db_session, user, session_id=1)
    answered_at = datetime(2026, 5, 14, 10, 0, tzinfo=UTC)
    answer = await _add_answer(
        db_session,
        answer_id=1,
        session_id=1,
        user=user,
        item_id="q1",
        is_correct=True,
        answered_at=answered_at,
    )

    progress = await service.record_answer_result(
        db_session,
        user.telegram_user_id,
        level="A1",
        theme="Alltag",
        is_correct=True,
        is_duplicate=False,
        item_id="q1",
        available_items_count=10,
        answered_at=answered_at,
        user_answer_id=answer.id,
    )

    assert progress.unique_items_seen == 1
    assert progress.available_items_count == 10
    assert progress.coverage_score == Decimal("10.00")


@pytest.mark.asyncio
async def test_record_answer_result_counts_repeated_item_once_for_coverage(db_session: AsyncSession) -> None:
    user_repo = _StaticUserRepository()
    service = _progress_service(user_repo)
    user = await user_repo.create_if_missing(db_session, telegram_user_id=1117)
    first_time = datetime(2026, 5, 14, 10, 0, tzinfo=UTC)
    second_time = datetime(2026, 5, 15, 10, 0, tzinfo=UTC)
    await _add_session(db_session, user, session_id=1)
    await _add_answer(
        db_session,
        answer_id=1,
        session_id=1,
        user=user,
        item_id="q1",
        is_correct=True,
        answered_at=first_time,
    )
    await service.record_answer_result(
        db_session,
        user.telegram_user_id,
        level="A1",
        theme="Alltag",
        is_correct=True,
        is_duplicate=False,
        item_id="q1",
        available_items_count=10,
        answered_at=first_time,
    )
    await _add_session(db_session, user, session_id=2)
    await _add_answer(
        db_session,
        answer_id=2,
        session_id=2,
        user=user,
        item_id="q1",
        is_correct=True,
        answered_at=second_time,
    )

    progress = await service.record_answer_result(
        db_session,
        user.telegram_user_id,
        level="A1",
        theme="Alltag",
        is_correct=True,
        is_duplicate=False,
        item_id="q1",
        available_items_count=10,
        answered_at=second_time,
    )

    assert progress.total_answered == 2
    assert progress.unique_items_seen == 1
    assert progress.coverage_score == Decimal("10.00")


@pytest.mark.asyncio
async def test_record_answer_result_uses_berlin_days_for_stability(db_session: AsyncSession) -> None:
    user_repo = _StaticUserRepository()
    service = _progress_service(user_repo)
    user = await user_repo.create_if_missing(db_session, telegram_user_id=1118)
    first_time = datetime(2026, 5, 14, 21, 30, tzinfo=UTC)
    second_time = datetime(2026, 5, 14, 22, 30, tzinfo=UTC)
    await _add_session(db_session, user, session_id=1)
    await _add_answer(
        db_session,
        answer_id=1,
        session_id=1,
        user=user,
        item_id="q1",
        is_correct=True,
        answered_at=first_time,
    )
    await service.record_answer_result(
        db_session,
        user.telegram_user_id,
        level="A1",
        theme="Alltag",
        is_correct=True,
        is_duplicate=False,
        item_id="q1",
        available_items_count=10,
        answered_at=first_time,
    )
    await _add_session(db_session, user, session_id=2)
    await _add_answer(
        db_session,
        answer_id=2,
        session_id=2,
        user=user,
        item_id="q1",
        is_correct=True,
        answered_at=second_time,
    )

    progress = await service.record_answer_result(
        db_session,
        user.telegram_user_id,
        level="A1",
        theme="Alltag",
        is_correct=True,
        is_duplicate=False,
        item_id="q1",
        available_items_count=10,
        answered_at=second_time,
    )

    assert progress.stability_score == Decimal("75.00")
