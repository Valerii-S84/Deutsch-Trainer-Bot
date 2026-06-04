from __future__ import annotations

import pytest

from app.quiz_bank.schemas import QuizQuestionsResponse
from app.repositories.quiz_sessions import QuizSessionStatus
from app.services.training_session import ActiveSessionConflictError, ActiveSessionNotFoundError, NoMoreQuestionsError
from tests.fakes.training_session import (
    FakeAnalyticsRepository,
    FakeAnswerRepository,
    FakeDatabaseSession,
    FakeQuestionReferenceRepository,
    FakeSessionItemRepository,
    FakeSessionRepository,
    FakeUserRepository,
    StubQuizBankService,
    make_training_service,
    question_payload,
)


@pytest.mark.asyncio
async def test_user_bootstrap_created_once_for_same_telegram_id() -> None:
    user_repo = FakeUserRepository()
    service = make_training_service_with_user_repo(user_repo)
    db = FakeDatabaseSession()

    await service.start_session(db, telegram_user_id=111, level="A1", theme="Alltag", total_questions=5, force_new=False)
    await service.start_session(db, telegram_user_id=111, level="A1", theme="Alltag", total_questions=5, force_new=True)

    user = await service.get_user(db, 111)
    assert user_repo.create_calls == 1
    assert user.id == 1


@pytest.mark.asyncio
async def test_start_session_rejects_existing_active_session_when_not_forced() -> None:
    service = make_training_service([])
    db = FakeDatabaseSession()

    await service.start_session(db, telegram_user_id=123, level="A1", theme="Alltag", total_questions=4, force_new=False)
    with pytest.raises(ActiveSessionConflictError):
        await service.start_session(db, telegram_user_id=123, level="A1", theme="Alltag", total_questions=4, force_new=False)


@pytest.mark.asyncio
async def test_current_question_creates_shown_item_lifecycle() -> None:
    service = make_training_service([question_payload(item_id="q_lifecycle")])
    db = FakeDatabaseSession()
    user_id = 322

    await service.start_session(db, telegram_user_id=user_id, level="A1", theme="Alltag", total_questions=2, force_new=False)
    question = await service.get_or_create_current_question(db, telegram_user_id=user_id, force_refresh=True)

    user = await service.get_user(db, user_id)
    active_session = await service._session_repo.get_active_for_user(db, user.id)  # type: ignore[attr-defined]
    session_item = await service._session_item_repo.get_by_session_item(  # type: ignore[attr-defined]
        db,
        session_id=question.session_id,
        item_id="q_lifecycle",
    )

    assert question.training_session_item_id is not None
    assert question.question_reference_id is not None
    assert question.metadata_snapshot == {"progress_theme_key": "alltag"}
    assert active_session is not None
    assert active_session.shown_questions_count == 1
    assert session_item is not None
    assert session_item.status == "shown"
    assert session_item.daily_limit_charged_at == "now"


@pytest.mark.asyncio
async def test_submit_answer_completes_session_and_clears_pending() -> None:
    service = make_training_service([question_payload(correct_answer="a2")])
    db = FakeDatabaseSession()
    user_id = 222

    await service.start_session(db, telegram_user_id=user_id, level="A1", theme="Alltag", total_questions=1, force_new=False)
    question = await service.get_or_create_current_question(db, telegram_user_id=user_id, force_refresh=True)

    result = await service.submit_answer(
        db,
        telegram_user_id=user_id,
        session_id=question.session_id,
        question_token=question.question_token,
        selected_option_id="a2",
    )

    user = await service.get_user(db, user_id)
    completed_session = await service._session_repo.get_by_id_for_user(db, question.session_id, user.id)  # type: ignore[attr-defined]
    session_item = await service._session_item_repo.get_by_session_item(  # type: ignore[attr-defined]
        db,
        session_id=question.session_id,
        item_id=question.question_id,
    )
    assert result.is_completed is True
    assert result.correct_answers == 1
    assert completed_session is not None
    assert completed_session.status == QuizSessionStatus.completed
    assert completed_session.api_metadata.get("pending_question") is None
    assert session_item is not None
    assert session_item.status == "answered"
    event_names = [event.event_name for event in service._analytics_repo.events]  # type: ignore[attr-defined]
    assert event_names == ["training_started", "question_answered", "training_completed", "result_shown"]


@pytest.mark.asyncio
async def test_completed_session_does_not_accept_new_answer() -> None:
    service = make_training_service([question_payload(correct_answer="a2")])
    db = FakeDatabaseSession()
    user_id = 223

    await service.start_session(db, telegram_user_id=user_id, level="A1", theme="Alltag", total_questions=1, force_new=False)
    question = await service.get_or_create_current_question(db, telegram_user_id=user_id, force_refresh=True)
    await service.submit_answer(
        db,
        telegram_user_id=user_id,
        session_id=question.session_id,
        question_token=question.question_token,
        selected_option_id="a2",
    )

    with pytest.raises(ActiveSessionNotFoundError):
        await service.submit_answer(
            db,
            telegram_user_id=user_id,
            session_id=question.session_id,
            question_token=question.question_token,
            selected_option_id="a2",
        )


@pytest.mark.asyncio
async def test_get_question_marks_session_failed_when_quiz_bank_empty() -> None:
    empty_batch = QuizQuestionsResponse(items=[], requested_count=1, returned_count=0, has_more=False)
    service = make_training_service([empty_batch])
    db = FakeDatabaseSession()
    user_id = 333

    await service.start_session(db, telegram_user_id=user_id, level="A1", theme="Alltag", total_questions=1, force_new=False)
    with pytest.raises(NoMoreQuestionsError):
        await service.get_or_create_current_question(db, telegram_user_id=user_id, force_refresh=True)

    user = await service.get_user(db, user_id)
    active = await service._session_repo.get_active_for_user(db, user.id)  # type: ignore[attr-defined]
    assert active is None


@pytest.mark.asyncio
async def test_force_new_session_replaces_existing_active() -> None:
    service = make_training_service([])
    db = FakeDatabaseSession()
    user_id = 444

    first = await service.start_session(db, telegram_user_id=user_id, level="A1", theme="Alltag", total_questions=3, force_new=False)
    second = await service.start_session(db, telegram_user_id=user_id, level="A1", theme="Beruf", total_questions=3, force_new=True)

    user = await service.get_user(db, user_id)
    active = await service._session_repo.get_active_for_user(db, user.id)  # type: ignore[attr-defined]
    assert active is not None
    assert active.id == second.id
    assert first.status == QuizSessionStatus.cancelled
    assert active.theme == "Beruf"


def make_training_service_with_user_repo(user_repo: FakeUserRepository):
    from app.services.training_session import TrainingSessionService

    return TrainingSessionService(
        user_repo=user_repo,
        session_repo=FakeSessionRepository(),
        answer_repo=FakeAnswerRepository(),
        analytics_repo=FakeAnalyticsRepository(),
        question_reference_repo=FakeQuestionReferenceRepository(),
        session_item_repo=FakeSessionItemRepository(),
        quiz_service=StubQuizBankService([]),
    )

