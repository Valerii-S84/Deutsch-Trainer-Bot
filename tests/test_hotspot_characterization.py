from __future__ import annotations

from contextlib import asynccontextmanager
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.bot.handlers import level as level_handlers
from app.bot.handlers import theme as theme_handlers
from app.bot.texts import LEVEL_SELECTED_TEXT, THEME_EMPTY_STATE_TEXT, TRAINING_NO_LEVEL_SELECTED_TEXT
from app.db.base import Base
from app.db.models import Progress, QuestionReference, QuizSession, TrainingSessionItem, User
from app.quiz_bank.errors import QuizBankUnavailableError
from app.quiz_bank.schemas import QuizTheme, QuizThemesResponse
from app.repositories.progress_history import ProgressHistoryRepository
from app.repositories.question_references import QuestionReferenceRepository
from app.repositories.training_session_items import TrainingSessionItemRepository
@pytest_asyncio.fixture
async def db_session() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with session_factory() as session:
        yield session
    await engine.dispose()
@asynccontextmanager
async def _session(db: SimpleNamespace):
    yield db
def _callback(*, data: str | None = None, user_id: int | None = 111) -> SimpleNamespace:
    from_user = SimpleNamespace(id=user_id) if user_id is not None else None
    return SimpleNamespace(data=data, from_user=from_user, message=SimpleNamespace(answer=AsyncMock()), answer=AsyncMock())
def _db() -> SimpleNamespace:
    return SimpleNamespace(flush=AsyncMock(), commit=AsyncMock(), rollback=AsyncMock())
def _user_repo(*, selected_level: str | None = None, persist_fails: bool = False) -> SimpleNamespace:
    side_effect = RuntimeError("persist failed") if persist_fails else None
    return SimpleNamespace(
        get_by_telegram_id=AsyncMock(return_value=SimpleNamespace(selected_level=selected_level)),
        set_training_preferences=AsyncMock(return_value=SimpleNamespace(id=1), side_effect=side_effect),
    )
def _quiz_service(*, themes: list[QuizTheme] | None = None, error: Exception | None = None) -> SimpleNamespace:
    if error is not None:
        return SimpleNamespace(get_themes=AsyncMock(side_effect=error))
    catalog = themes if themes is not None else [_theme()]
    return SimpleNamespace(get_themes=AsyncMock(return_value=QuizThemesResponse(level="A1", themes=catalog)))
def _theme() -> QuizTheme:
    return QuizTheme(theme="Alltag", theme_key="alltag", is_active=True, available_items_count=3)
@pytest.mark.asyncio
async def test_theme_selection_without_user_id_falls_back_to_levels() -> None:
    callback = _callback(user_id=None)
    await theme_handlers.open_theme_selection(callback)
    callback.answer.assert_awaited_once()
    assert callback.message.answer.await_args.args[0] == TRAINING_NO_LEVEL_SELECTED_TEXT

@pytest.mark.asyncio
async def test_theme_selection_handles_empty_and_unavailable_catalog(monkeypatch) -> None:
    db = _db()
    callback = _callback()
    monkeypatch.setattr(theme_handlers, "_session_factory", lambda: _session(db))
    monkeypatch.setattr(theme_handlers, "_user_repo", _user_repo(selected_level="A1"))
    monkeypatch.setattr(theme_handlers, "_quiz_service", lambda: _quiz_service(themes=[]))
    await theme_handlers.open_theme_selection(callback)
    assert callback.message.answer.await_args.args[0] == THEME_EMPTY_STATE_TEXT
    failing_callback = _callback()
    monkeypatch.setattr(theme_handlers, "_quiz_service", lambda: _quiz_service(error=QuizBankUnavailableError("down")))
    await theme_handlers.open_theme_selection(failing_callback)
    assert failing_callback.message.answer.await_args.kwargs["reply_markup"] is not None

@pytest.mark.asyncio
async def test_level_selection_rolls_back_persist_errors_and_still_uses_quiz_bank(monkeypatch) -> None:
    menu_callback = _callback()
    await level_handlers.open_level_selection(menu_callback)
    invalid_callback = _callback(data="level:ZZ")
    await level_handlers.level_selected(invalid_callback)
    db = _db()
    callback = _callback(data="level:A1")
    monkeypatch.setattr(level_handlers, "_session_factory", lambda: _session(db))
    monkeypatch.setattr(level_handlers, "_user_repo", _user_repo(persist_fails=True))
    monkeypatch.setattr(level_handlers, "_analytics_tracker", SimpleNamespace(record=AsyncMock()))
    monkeypatch.setattr(level_handlers, "_quiz_service", lambda: _quiz_service())
    await level_handlers.level_selected(callback)
    db.rollback.assert_awaited_once()
    assert callback.message.answer.await_args.args[0] == LEVEL_SELECTED_TEXT.format(level="A1")
    error_db = _db()
    error_callback = _callback(data="level:A1")
    monkeypatch.setattr(level_handlers, "_session_factory", lambda: _session(error_db))
    monkeypatch.setattr(level_handlers, "_user_repo", _user_repo())
    monkeypatch.setattr(level_handlers, "_quiz_service", lambda: _quiz_service(error=QuizBankUnavailableError("down")))
    await level_handlers.level_selected(error_callback)
    error_db.commit.assert_awaited_once()
    assert error_callback.message.answer.await_args.kwargs["reply_markup"] is not None

@pytest.mark.asyncio
async def test_level_selection_reports_empty_catalog_without_user_context(monkeypatch) -> None:
    callback = _callback(data="level:A1", user_id=None)
    monkeypatch.setattr(level_handlers, "_quiz_service", lambda: _quiz_service(themes=[]))
    await level_handlers.level_selected(callback)
    assert callback.message.answer.await_args.args[0] == THEME_EMPTY_STATE_TEXT

async def _upsert_reference(repository: QuestionReferenceRepository, db: AsyncSession, **overrides: object) -> QuestionReference:
    values = dict(
        item_id="item-1",
        level="A1",
        theme="Alltag",
        theme_key=None,
        metadata_snapshot=None,
        content_version=None,
        question_text_snapshot=None,
        correct_answer_snapshot=None,
        explanation_snapshot=None,
    ) | overrides
    return await repository.upsert_snapshot(db, **values)  # type: ignore[arg-type]

@pytest.mark.asyncio
async def test_question_reference_upsert_creates_updates_and_keeps_single_row(db_session: AsyncSession) -> None:
    repository = QuestionReferenceRepository()
    created = await _upsert_reference(repository, db_session)
    await db_session.flush()
    updated = await _upsert_reference(
        repository,
        db_session,
        level="B1",
        theme="Beruf",
        theme_key="beruf",
        metadata_snapshot={"source": "contract"},
        content_version="v2",
    )
    assert updated is created
    assert (await repository.get_by_item_id(db_session, "missing")) is None
    assert created.metadata_snapshot == {"source": "contract"}
    assert await db_session.scalar(select(func.count(QuestionReference.id))) == 1


@pytest.mark.asyncio
async def test_question_reference_upsert_ignores_catalog_scoped_rows(db_session: AsyncSession) -> None:
    repository = QuestionReferenceRepository()
    catalog_reference = QuestionReference(
        id=1,
        catalog_id="catalog-de",
        item_id="item-1",
        item_version="v1",
        level="A1",
        theme="Alltag",
        source="local_quiz_catalog",
    )
    db_session.add(catalog_reference)
    await db_session.flush()

    api_reference = await _upsert_reference(repository, db_session)
    await db_session.flush()

    assert api_reference is not catalog_reference
    assert api_reference.catalog_id is None
    assert api_reference.item_version is None
    assert catalog_reference.source == "local_quiz_catalog"
    assert await db_session.scalar(select(func.count(QuestionReference.id))) == 2


@pytest.mark.asyncio
async def test_progress_history_records_snapshot_and_delta(db_session: AsyncSession) -> None:
    db_session.add(User(id=1, telegram_user_id=1001))
    progress = Progress(
        id=1, user_id=1, level="A1", theme="Alltag", total_answered=3, total_correct=2,
        wrong_count=1, accuracy=Decimal("66.67"), coverage_score=Decimal("25.50"),
        topic_status="learning", unique_items_seen=2,
    )
    db_session.add(progress)
    await db_session.flush()
    history = await ProgressHistoryRepository().record_answer_change(
        db_session,
        progress=progress,
        previous_status="new",
        previous_scores={"total_answered": 1, "total_correct": 1, "wrong_count": 0, "unique_items_seen": 1},
        session_id=None,
        user_answer_id=None,
        reason_code="answer_submitted",
    )
    assert history.event_type == "answer_recorded"
    assert history.new_scores["coverage_score"] == 25.5
    assert history.delta["answered_delta"] == 2
    assert history.delta["coverage_delta"] is None

def test_progress_history_snapshot_handles_empty_and_invalid_numbers() -> None:
    progress = SimpleNamespace(
        total_answered=None, total_correct=None, wrong_count=None, accuracy="bad",
        coverage_score=Decimal("10.25"), coverage_status="known", stability_score="bad",
        weakness_score=None, recency_score=Decimal("5.50"), unique_items_seen=None,
        available_items_count=None, topic_status="new",
    )
    snapshot = ProgressHistoryRepository.snapshot_scores(progress)
    assert snapshot["total_answered"] == 0
    assert snapshot["accuracy"] is None
    assert snapshot["coverage_score"] == 10.25
    assert snapshot["stability_score"] is None

@pytest.mark.asyncio
async def test_training_session_item_lifecycle_is_idempotent(db_session: AsyncSession) -> None:
    db_session.add_all([
        User(id=1, telegram_user_id=1001),
        QuizSession(id=1, user_id=1, level="A1", theme="Alltag"),
        QuestionReference(id=1, item_id="item-1", level="A1", theme="Alltag"),
    ])
    await db_session.flush()
    repository = TrainingSessionItemRepository()
    item = await repository.create_shown(db_session, session_id=1, user_id=1, question_reference_id=1, item_id="item-1", position=1)
    await db_session.flush()
    duplicate = await repository.create_shown(db_session, session_id=1, user_id=1, question_reference_id=1, item_id="item-1", position=2)
    charged = await repository.mark_daily_limit_charged(db_session, duplicate, daily_limit_id=9)
    answered = await repository.mark_answered(db_session, charged)
    assert duplicate is item
    assert charged.daily_limit_id == 9
    assert answered.status == "answered"
    assert await db_session.scalar(select(func.count(TrainingSessionItem.id))) == 1

@pytest.mark.asyncio
async def test_training_session_item_cannot_charge_before_being_shown(db_session: AsyncSession) -> None:
    with pytest.raises(ValueError, match="after an item is shown"):
        await TrainingSessionItemRepository().mark_daily_limit_charged(db_session, TrainingSessionItem())
