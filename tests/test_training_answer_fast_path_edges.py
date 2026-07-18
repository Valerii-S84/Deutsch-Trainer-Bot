from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from app.repositories.answers import AnswerWriteResult
from app.services.training_answer_fast_path import (
    ACTIVE_SESSION_STATUS,
    FastPathContext,
    SessionState,
    accept_answer_fast_path,
    _accepted_result,
    _answer_accepted_payload,
    _answer_data,
    _build_fast_path_context,
    _dialect_name,
    _duplicate_result,
    _current_session_state,
    _ensure_connection_acquired,
    _mark_session_item_answered,
    _session_type,
    _update_session_state,
)
from app.services.training_payloads import ActiveSessionNotFoundError, QuestionStateError
from tests.test_answer_write_behind_pipeline import _pending_payload


def test_build_context_uses_cached_pending_and_source_flow() -> None:
    pending = _pending_payload()

    context = _build_fast_path_context(
        _row(
            api_metadata={"pending_question": {"unused": True}},
            source_metadata={"flow": "weak_theme"},
        ),
        cached_pending=pending,
        question_token="tok1",
        selected_option_id="a2",
    )

    assert context.pending == pending
    assert context.session_type == "weak_theme"
    assert context.correct_answer_text == "Antwort B"
    assert context.selected_option_id == "a2"


def test_build_context_restores_pending_from_metadata_when_cache_misses() -> None:
    pending = _pending_payload()

    context = _build_fast_path_context(
        _row(api_metadata={"pending_question": _payload_dict(pending)}),
        cached_pending=None,
        question_token="tok1",
        selected_option_id="a1",
    )

    assert context.pending.question_token == "tok1"
    assert context.pending.session_id == 1


def test_build_context_rejects_inactive_stale_or_invalid_answer() -> None:
    pending = _pending_payload()

    with pytest.raises(ActiveSessionNotFoundError, match="not found"):
        _build_fast_path_context(
            None,
            cached_pending=pending,
            question_token="tok1",
            selected_option_id="a1",
        )
    with pytest.raises(ActiveSessionNotFoundError, match="not active"):
        _build_fast_path_context(
            _row(status="completed"),
            cached_pending=pending,
            question_token="tok1",
            selected_option_id="a1",
        )
    with pytest.raises(QuestionStateError, match="stale"):
        _build_fast_path_context(
            _row(),
            cached_pending=replace(pending, question_token="old-token"),
            question_token="tok1",
            selected_option_id="a1",
        )
    with pytest.raises(QuestionStateError, match="invalid"):
        _build_fast_path_context(
            _row(),
            cached_pending=pending,
            question_token="tok1",
            selected_option_id="missing",
        )


def test_result_payload_and_answer_data_preserve_idempotent_answer_context() -> None:
    context = _context()
    state = SessionState(answered_count=5, correct_answers=4, total_questions=5, completed=True)
    answer = AnswerWriteResult(
        id=123,
        session_id=1,
        user_id=1,
        external_quiz_id="q1",
        selected_answer="a2",
        correct_answer="a2",
        is_correct=True,
        answered_at=datetime(2026, 1, 2, 3, 4, tzinfo=UTC),
        created=True,
    )

    result = _accepted_result(context, state, is_correct=True)
    duplicate = _duplicate_result(context, state, replace(answer, created=False))
    payload = _answer_accepted_payload(context, state, answer=answer, is_correct=True, result=result)
    data = _answer_data(context, is_correct=True, telegram_update_id=9001)

    assert result.is_completed is True
    assert result.recommendation_text == "Starte eine neue Runde, um weiter zu \u00fcben."
    assert duplicate.is_duplicate is True
    assert payload["answer_id"] == 123
    assert payload["session_completed"] is True
    assert payload["theme_id"] == "T01"
    assert payload["available_items_count"] == 10
    assert data.telegram_update_id == 9001
    assert data.content_fields.catalog_id == "cat"
    assert data.training_session_item_id == 11


def test_session_type_and_dialect_fallbacks() -> None:
    assert _session_type(None, None) == "regular"
    assert _session_type("custom", {}) == "custom"
    assert _dialect_name(SimpleNamespace(get_bind=lambda: None)) == ""
    assert _dialect_name(SimpleNamespace(get_bind=lambda: SimpleNamespace(dialect=SimpleNamespace(name="postgresql")))) == "postgresql"


@pytest.mark.asyncio
async def test_accept_answer_fast_path_persists_new_answer_updates_session_and_enqueues_outbox(monkeypatch) -> None:
    context = _context()
    state = SessionState(answered_count=5, correct_answers=4, total_questions=5, completed=True)
    answer = _answer_result(created=True)
    service = _FastPathService(answer)
    db = _PostgresDb()
    calls: list[str] = []

    async def validate_context(_db, **kwargs):
        assert kwargs["telegram_user_id"] == 700001
        assert kwargs["selected_option_id"] == "a2"
        return context

    async def mark_session_item_answered(_db, _context):
        calls.append("item")

    async def update_session_state(_db, _context, *, is_correct):
        assert is_correct is True
        calls.append("session")
        return state

    async def delete_cached_pending_question_if_enabled(**kwargs):
        calls.append(f"delete:{kwargs['session_id']}:{kwargs['question_token']}")

    monkeypatch.setattr("app.services.training_answer_fast_path._validate_context", validate_context)
    monkeypatch.setattr("app.services.training_answer_fast_path._mark_session_item_answered", mark_session_item_answered)
    monkeypatch.setattr("app.services.training_answer_fast_path._update_session_state", update_session_state)
    monkeypatch.setattr(
        "app.services.training_answer_fast_path.delete_cached_pending_question_if_enabled",
        delete_cached_pending_question_if_enabled,
    )

    result = await accept_answer_fast_path(
        service,
        db,
        telegram_user_id=700001,
        session_id=1,
        question_token="tok1",
        selected_option_id="a2",
        telegram_update_id=9001,
    )

    assert result is not None
    assert result.is_correct is True
    assert result.is_completed is True
    assert calls == ["item", "session", "delete:1:tok1"]
    assert service.answer_repo.created_data.telegram_update_id == 9001
    assert service.outbox_repo.events[0]["event_type"] == "answer.accepted"
    assert service.outbox_repo.events[0]["payload"]["answer_id"] == 123


@pytest.mark.asyncio
async def test_accept_answer_fast_path_duplicate_returns_existing_result_without_side_effects(monkeypatch) -> None:
    context = _context()
    state = SessionState(answered_count=2, correct_answers=1, total_questions=5, completed=False)
    service = _FastPathService(_answer_result(created=False, is_correct=False))
    db = _PostgresDb()

    async def validate_context(_db, **_kwargs):
        return context

    async def current_session_state(_db, *, session_id):
        assert session_id == 1
        return state

    async def unexpected(*_args, **_kwargs):
        raise AssertionError("duplicate answer must not mutate session or outbox")

    monkeypatch.setattr("app.services.training_answer_fast_path._validate_context", validate_context)
    monkeypatch.setattr("app.services.training_answer_fast_path._current_session_state", current_session_state)
    monkeypatch.setattr("app.services.training_answer_fast_path._mark_session_item_answered", unexpected)
    monkeypatch.setattr("app.services.training_answer_fast_path._update_session_state", unexpected)

    result = await accept_answer_fast_path(
        service,
        db,
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
async def test_accept_answer_fast_path_ignores_non_postgres_sessions() -> None:
    result = await accept_answer_fast_path(
        _FastPathService(_answer_result(created=True)),
        SimpleNamespace(get_bind=lambda: SimpleNamespace(dialect=SimpleNamespace(name="sqlite"))),
        telegram_user_id=700001,
        session_id=1,
        question_token="tok1",
        selected_option_id="a2",
        telegram_update_id=9001,
    )

    assert result is None


@pytest.mark.asyncio
async def test_fast_path_db_helpers_update_item_by_id_or_question_and_complete_session() -> None:
    pending = _pending_payload()
    context = _context()
    db = _DbExecuteSpy()

    await _mark_session_item_answered(db, context)
    await _mark_session_item_answered(db, replace_context(context, pending=replace(pending, training_session_item_id=None)))
    incomplete = await _update_session_state(db, replace_context(context, answered_count=1), is_correct=False)
    completed = await _update_session_state(db, replace_context(context, answered_count=4), is_correct=True)

    assert len(db.statements) == 4
    assert incomplete.completed is False
    assert incomplete.correct_answers == 3
    assert completed.completed is True
    assert completed.correct_answers == 4


@pytest.mark.asyncio
async def test_fast_path_connection_and_current_state_helpers() -> None:
    db = _DbExecuteSpy(
        row=SimpleNamespace(
            answered_count=5,
            correct_answers=4,
            total_questions=5,
            status="completed",
        )
    )

    await _ensure_connection_acquired(db)
    state = await _current_session_state(db, session_id=1)

    assert db.connection_acquired is True
    assert state.completed is True
    assert state.correct_answers == 4


def _context() -> FastPathContext:
    pending = _pending_payload()
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
        api_metadata={"pending_question": _payload_dict(pending), "keep": True},
    )


def replace_context(context: FastPathContext, **changes: object) -> FastPathContext:
    values = {
        "telegram_user_id": context.telegram_user_id,
        "user_id": context.user_id,
        "session_id": context.session_id,
        "session_type": context.session_type,
        "total_questions": context.total_questions,
        "answered_count": context.answered_count,
        "correct_answers": context.correct_answers,
        "pending": context.pending,
        "selected_option_id": context.selected_option_id,
        "correct_answer_text": context.correct_answer_text,
        "api_metadata": context.api_metadata,
    }
    values.update(changes)
    return FastPathContext(**values)


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


class _DbExecuteSpy:
    def __init__(self, *, row=None) -> None:
        self.statements: list[object] = []
        self.connection_acquired = False
        self._row = row

    async def connection(self) -> None:
        self.connection_acquired = True

    async def execute(self, statement):
        self.statements.append(statement)
        return _OneResult(self._row)


class _OneResult:
    def __init__(self, row) -> None:
        self._row = row

    def one(self):
        return self._row


def _row(**overrides: object) -> dict[str, object]:
    pending = _pending_payload()
    row = {
        "user_id": 1,
        "telegram_user_id": 700001,
        "session_id": 1,
        "status": ACTIVE_SESSION_STATUS,
        "session_type": "regular",
        "source_metadata": {},
        "source": "local_quiz_catalog",
        "total_questions": 5,
        "answered_count": 0,
        "correct_answers": 0,
        "api_metadata": {"pending_question": _payload_dict(pending)},
    }
    row.update(overrides)
    return row


def _payload_dict(payload) -> dict[str, object]:
    from app.services.training_payloads import serialize_question_payload

    return serialize_question_payload(payload)
