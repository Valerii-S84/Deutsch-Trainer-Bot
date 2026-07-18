from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from app.repositories.answers import AnswerWriteResult
from app.services.training_answer_fast_path import (
    FastPathContext,
    SessionState,
    _accepted_result,
    _answer_accepted_payload,
    _answer_data,
    accept_answer_fast_path,
)
from app.services.training_payloads import QuestionStateError, QuizQuestionPayload


def test_fast_path_result_payload_and_answer_data_preserve_context() -> None:
    context = _context()
    state = SessionState(
        answered_count=5, correct_answers=4, total_questions=5, completed=True
    )

    result = _accepted_result(context, state, is_correct=True)
    payload = _answer_accepted_payload(
        context,
        state,
        answer=_answer_result(created=True),
        is_correct=True,
        result=result,
    )
    data = _answer_data(context, is_correct=True, telegram_update_id=9001)

    assert result.is_completed is True
    assert result.recommendation_text == "Starte eine neue Runde, um weiter zu üben."
    assert payload["answer_id"] == 123
    assert payload["available_items_count"] == 10
    assert payload["session_completed"] is True
    assert data.telegram_update_id == 9001
    assert data.training_session_item_id == 11
    assert data.content_fields.catalog_id == "cat"


@pytest.mark.asyncio
async def test_fast_path_accepts_answer_updates_session_and_enqueues_outbox(
    monkeypatch,
) -> None:
    context = _context()
    state = SessionState(
        answered_count=5, correct_answers=4, total_questions=5, completed=True
    )
    service = _FastPathService(_answer_result(created=True))
    calls: list[str] = []
    _patch_success_flow(monkeypatch, context, state, calls)

    result = await accept_answer_fast_path(
        service,
        _PostgresDb(),
        telegram_user_id=700001,
        session_id=1,
        question_token="tok1",
        selected_option_id="a2",
        telegram_update_id=9001,
    )

    assert result is not None
    assert result.is_correct is True
    assert result.is_completed is True
    assert calls == ["item", "session"]
    assert service.answer_repo.created_data.telegram_update_id == 9001
    assert service.outbox_repo.events[0]["event_type"] == "answer.accepted"
    assert service.outbox_repo.events[0]["payload"]["answer_id"] == 123


@pytest.mark.asyncio
async def test_fast_path_duplicate_has_no_mutating_side_effects(monkeypatch) -> None:
    context = _context()
    state = SessionState(
        answered_count=2, correct_answers=1, total_questions=5, completed=False
    )
    service = _FastPathService(_answer_result(created=False, is_correct=False))

    async def validate_context(_db, **_kwargs):
        return context

    async def current_session_state(_db, *, session_id):
        assert session_id == 1
        return state

    async def unexpected(*_args, **_kwargs):
        raise AssertionError("duplicate answer must not mutate session state")

    monkeypatch.setattr(
        "app.services.training_answer_fast_path._validate_context", validate_context
    )
    monkeypatch.setattr(
        "app.services.training_answer_fast_path._current_session_state",
        current_session_state,
    )
    monkeypatch.setattr(
        "app.services.training_answer_fast_path._mark_session_item_answered", unexpected
    )
    monkeypatch.setattr(
        "app.services.training_answer_fast_path._update_session_state", unexpected
    )

    result = await accept_answer_fast_path(
        service,
        _PostgresDb(),
        telegram_user_id=700001,
        session_id=1,
        question_token="tok1",
        selected_option_id="a2",
        telegram_update_id=9001,
    )

    assert result is not None
    assert result.is_duplicate is True
    assert result.is_correct is False
    assert service.outbox_repo.events == []


@pytest.mark.asyncio
async def test_fast_path_rejects_duplicate_from_another_session(monkeypatch) -> None:
    context = _context()
    answer = AnswerWriteResult(
        id=123,
        session_id=99,
        user_id=1,
        external_quiz_id="q1",
        selected_answer="a2",
        correct_answer="a2",
        is_correct=True,
        answered_at=datetime(2026, 1, 2, 3, 4, tzinfo=UTC),
        created=False,
    )

    async def validate_context(_db, **_kwargs):
        return context

    monkeypatch.setattr(
        "app.services.training_answer_fast_path._validate_context", validate_context
    )

    with pytest.raises(QuestionStateError, match="another session"):
        await accept_answer_fast_path(
            _FastPathService(answer),
            _PostgresDb(),
            telegram_user_id=700001,
            session_id=1,
            question_token="tok1",
            selected_option_id="a2",
            telegram_update_id=9001,
        )


@pytest.mark.asyncio
async def test_fast_path_defers_non_postgres_sessions() -> None:
    db = SimpleNamespace(
        get_bind=lambda: SimpleNamespace(dialect=SimpleNamespace(name="sqlite"))
    )

    result = await accept_answer_fast_path(
        _FastPathService(_answer_result(created=True)),
        db,
        telegram_user_id=700001,
        session_id=1,
        question_token="tok1",
        selected_option_id="a2",
        telegram_update_id=9001,
    )

    assert result is None


def _patch_success_flow(monkeypatch, context, state, calls) -> None:
    async def validate_context(_db, **kwargs):
        assert kwargs == {
            "telegram_user_id": 700001,
            "session_id": 1,
            "question_token": "tok1",
            "selected_option_id": "a2",
        }
        return context

    async def mark_session_item_answered(_db, actual_context):
        assert actual_context == context
        calls.append("item")

    async def update_session_state(_db, actual_context, *, is_correct):
        assert actual_context == context
        assert is_correct is True
        calls.append("session")
        return state

    monkeypatch.setattr(
        "app.services.training_answer_fast_path._validate_context", validate_context
    )
    monkeypatch.setattr(
        "app.services.training_answer_fast_path._mark_session_item_answered",
        mark_session_item_answered,
    )
    monkeypatch.setattr(
        "app.services.training_answer_fast_path._update_session_state",
        update_session_state,
    )


def _context() -> FastPathContext:
    pending = QuizQuestionPayload(
        session_id=1,
        question_token="tok1",
        question_id="q1",
        question_text="Was ist korrekt?",
        answer_options=(("a1", "Antwort A"), ("a2", "Antwort B")),
        correct_answer="a2",
        explanation="Richtig erklärt.",
        position=1,
        total_questions=5,
        level="A1",
        theme="Alltag",
        correct_answer_text="Antwort B",
        theme_key="alltag",
        content_version="1.0",
        metadata_snapshot={"catalog_id": "cat", "available_items_count": 10},
        question_reference_id=1,
        training_session_item_id=11,
    )
    return FastPathContext(
        telegram_user_id=700001,
        user_id=1,
        session_id=1,
        session_type="regular",
        total_questions=5,
        answered_count=4,
        correct_answers=3,
        pending=pending,
        selected_option_id="a2",
        correct_answer_text="Antwort B",
        api_metadata={"pending_question": {"question_token": "tok1"}, "keep": True},
    )


def _answer_result(*, created: bool, is_correct: bool = True) -> AnswerWriteResult:
    return AnswerWriteResult(
        id=123,
        session_id=1,
        user_id=1,
        external_quiz_id="q1",
        selected_answer="a2",
        correct_answer="a2",
        is_correct=is_correct,
        answered_at=datetime(2026, 1, 2, 3, 4, tzinfo=UTC),
        created=created,
    )


class _FastPathService:
    def __init__(self, answer: AnswerWriteResult) -> None:
        self.answer_repo = _AnswerRepoSpy(answer)
        self.outbox_repo = _OutboxRepoSpy()
        self._answer_repo = self.answer_repo
        self._outbox_repo = self.outbox_repo


class _AnswerRepoSpy:
    def __init__(self, answer: AnswerWriteResult) -> None:
        self._answer = answer
        self.created_data = None

    async def create_idempotent(self, _db, data):
        self.created_data = data
        return self._answer


class _OutboxRepoSpy:
    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []

    async def enqueue(self, _db, **kwargs):
        self.events.append(kwargs)


class _PostgresDb:
    def get_bind(self):
        return SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))
