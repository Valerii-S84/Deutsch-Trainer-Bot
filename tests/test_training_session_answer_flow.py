from __future__ import annotations

import pytest

from app.services.training_session import ActiveSessionNotFoundError, QuestionStateError
from tests.fakes.training_session import FakeDatabaseSession, make_training_service, question_payload


@pytest.mark.asyncio
async def test_submit_answer_marks_score_once_for_duplicate_click() -> None:
    service = make_training_service([question_payload()])
    db = FakeDatabaseSession()
    user_id = 321

    await service.start_session(db, telegram_user_id=user_id, level="A1", theme="Alltag", total_questions=2, force_new=False)
    question = await service.get_or_create_current_question(db, telegram_user_id=user_id, force_refresh=True)

    first = await service.submit_answer(
        db,
        telegram_user_id=user_id,
        session_id=question.session_id,
        question_token=question.question_token,
        selected_option_id="a1",
    )
    second = await service.submit_answer(
        db,
        telegram_user_id=user_id,
        session_id=question.session_id,
        question_token=question.question_token,
        selected_option_id="a1",
    )

    assert first.is_correct is False
    assert first.is_duplicate is False
    assert second.is_duplicate is True
    assert first.correct_answers == 0
    assert second.correct_answers == 0

    user = await service.get_user(db, user_id)
    active_session = await service._session_repo.get_active_for_user(db, user.id)  # type: ignore[attr-defined]
    assert active_session is not None
    assert active_session.correct_answers == 0


@pytest.mark.asyncio
async def test_submit_answer_is_idempotent_by_telegram_update_id() -> None:
    service = make_training_service([question_payload()])
    db = FakeDatabaseSession()
    user_id = 325

    await service.start_session(db, telegram_user_id=user_id, level="A1", theme="Alltag", total_questions=2, force_new=False)
    question = await service.get_or_create_current_question(db, telegram_user_id=user_id, force_refresh=True)

    first = await service.submit_answer(
        db,
        telegram_user_id=user_id,
        session_id=question.session_id,
        question_token=question.question_token,
        selected_option_id="a1",
        telegram_update_id=998001,
    )
    second = await service.submit_answer(
        db,
        telegram_user_id=user_id,
        session_id=question.session_id,
        question_token=question.question_token,
        selected_option_id="a1",
        telegram_update_id=998001,
    )

    assert first.is_duplicate is False
    assert second.is_duplicate is True
    assert service._answer_repo.create_calls == 1  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_get_next_question_rejects_stale_token_before_fetching() -> None:
    service = make_training_service([question_payload(item_id="q1"), question_payload(item_id="q2")])
    db = FakeDatabaseSession()
    user_id = 323

    await service.start_session(db, telegram_user_id=user_id, level="A1", theme="Alltag", total_questions=2, force_new=False)
    question = await service.get_or_create_current_question(db, telegram_user_id=user_id, force_refresh=True)

    with pytest.raises(QuestionStateError):
        await service.get_next_question(
            db,
            telegram_user_id=user_id,
            session_id=question.session_id,
            answered_question_token="stale",
        )

    assert len(service._quiz_service.calls) == 1  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_submit_answer_rejects_unknown_option_without_answer_row() -> None:
    service = make_training_service([question_payload()])
    db = FakeDatabaseSession()
    user_id = 324

    await service.start_session(db, telegram_user_id=user_id, level="A1", theme="Alltag", total_questions=2, force_new=False)
    question = await service.get_or_create_current_question(db, telegram_user_id=user_id, force_refresh=True)

    with pytest.raises(QuestionStateError):
        await service.submit_answer(
            db,
            telegram_user_id=user_id,
            session_id=question.session_id,
            question_token=question.question_token,
            selected_option_id="unknown",
        )

    assert service._answer_repo.create_calls == 0  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_submit_answer_from_another_user_is_rejected() -> None:
    service = make_training_service([question_payload()])
    db = FakeDatabaseSession()

    await service.start_session(db, telegram_user_id=401, level="A1", theme="Alltag", total_questions=2, force_new=False)
    question = await service.get_or_create_current_question(db, telegram_user_id=401, force_refresh=True)

    with pytest.raises(ActiveSessionNotFoundError):
        await service.submit_answer(
            db,
            telegram_user_id=402,
            session_id=question.session_id,
            question_token=question.question_token,
            selected_option_id="a2",
        )

    assert service._answer_repo.create_calls == 0  # type: ignore[attr-defined]

