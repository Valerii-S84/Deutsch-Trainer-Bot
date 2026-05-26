from __future__ import annotations

import pytest

from app.quiz_bank.errors import QuizBankUnavailableError
from app.services.entitlements import DailyLimitExceededError
from app.services.training_session import TrainingSessionService
from tests.fakes.training_session import (
    FailingQuizBankService,
    FakeAnalyticsRepository,
    FakeAnswerRepository,
    FakeApiErrorLogRepository,
    FakeDatabaseSession,
    FakeEntitlementService,
    FakeQuestionReferenceRepository,
    FakeSessionItemRepository,
    FakeSessionRepository,
    FakeUserRepository,
    StubQuizBankService,
    question_payload,
)


@pytest.mark.asyncio
async def test_quiz_bank_failure_is_persisted_without_answer_or_limit_charge() -> None:
    answer_repo = FakeAnswerRepository()
    api_error_repo = FakeApiErrorLogRepository()
    entitlement_service = FakeEntitlementService()
    service = TrainingSessionService(
        user_repo=FakeUserRepository(),
        session_repo=FakeSessionRepository(),
        answer_repo=answer_repo,
        analytics_repo=FakeAnalyticsRepository(),
        api_error_log_repo=api_error_repo,
        question_reference_repo=FakeQuestionReferenceRepository(),
        session_item_repo=FakeSessionItemRepository(),
        quiz_service=FailingQuizBankService(),
        entitlement_service=entitlement_service,
    )
    db = FakeDatabaseSession()
    user_id = 336

    await service.start_session(db, telegram_user_id=user_id, level="A1", theme="Alltag", total_questions=1, force_new=False)
    with pytest.raises(QuizBankUnavailableError):
        await service.get_or_create_current_question(db, telegram_user_id=user_id, force_refresh=True)

    assert answer_repo.create_calls == 0
    assert entitlement_service.charge_calls == 0
    assert api_error_repo.records == [
        {
            "endpoint": "/questions",
            "error_category": "unavailable",
            "user_id": 1,
            "session_id": 1,
            "request_id": "qb-test",
            "status_code": 503,
            "level": "A1",
            "theme": "Alltag",
            "error_metadata": {"message": "Quiz Bank down"},
        },
    ]


@pytest.mark.asyncio
async def test_get_question_charges_daily_limit_when_question_is_shown() -> None:
    entitlement_service = FakeEntitlementService()
    service = TrainingSessionService(
        user_repo=FakeUserRepository(),
        session_repo=FakeSessionRepository(),
        answer_repo=FakeAnswerRepository(),
        analytics_repo=FakeAnalyticsRepository(),
        question_reference_repo=FakeQuestionReferenceRepository(),
        session_item_repo=FakeSessionItemRepository(),
        quiz_service=StubQuizBankService([question_payload(item_id="q_limit")]),
        entitlement_service=entitlement_service,
    )
    db = FakeDatabaseSession()
    user_id = 334

    await service.start_session(
        db,
        telegram_user_id=user_id,
        level="A1",
        theme="Alltag",
        total_questions=1,
        force_new=False,
    )
    question = await service.get_or_create_current_question(db, telegram_user_id=user_id, force_refresh=True)
    session_item = await service._session_item_repo.get_by_session_item(  # type: ignore[attr-defined]
        db,
        session_id=question.session_id,
        item_id="q_limit",
    )

    assert entitlement_service.charge_calls == 1
    assert session_item is not None
    assert session_item.daily_limit_charged_at == "now"
    assert session_item.daily_limit_id == 77


@pytest.mark.asyncio
async def test_daily_limit_hit_blocks_quiz_request_before_api_call() -> None:
    entitlement_service = FakeEntitlementService(limit_exceeded=True)
    quiz_service = StubQuizBankService([question_payload(item_id="q_never")])
    service = TrainingSessionService(
        user_repo=FakeUserRepository(),
        session_repo=FakeSessionRepository(),
        answer_repo=FakeAnswerRepository(),
        analytics_repo=FakeAnalyticsRepository(),
        question_reference_repo=FakeQuestionReferenceRepository(),
        session_item_repo=FakeSessionItemRepository(),
        quiz_service=quiz_service,
        entitlement_service=entitlement_service,
    )
    db = FakeDatabaseSession()

    with pytest.raises(DailyLimitExceededError):
        await service.start_session(
            db,
            telegram_user_id=335,
            level="A1",
            theme="Alltag",
            total_questions=1,
            force_new=False,
        )

    assert quiz_service.calls == []

