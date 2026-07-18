from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.bot.handlers import training
from app.bot.texts import PAYWALL_DAILY_LIMIT_TEXT, TRAINING_QUESTION_TEMPLATE
from app.services.training_session import ActiveSessionNotFoundError, AnswerResult
from tests.test_training_handlers import (
    FakeDb,
    _Callback,
    _daily_limit_error,
    _extract_text,
    _patch_service,
    _question,
)


def test_theme_payload_needs_level_detects_legacy_or_empty_level_callbacks() -> None:
    assert training._theme_payload_needs_level("theme:A1") is True
    assert training._theme_payload_needs_level("theme::T01") is True
    assert training._theme_payload_needs_level("theme:A1:T01") is False
    assert training._theme_payload_needs_level("train:next:1:tok") is False


@pytest.mark.asyncio
async def test_handle_resume_training_rejects_mismatched_active_session(monkeypatch) -> None:
    db = FakeDb()
    service = AsyncMock()
    service.get_active_session.return_value = SimpleNamespace(id=99)
    _patch_service(monkeypatch, service, db)

    callback = _Callback(data="train:resume:10")

    await training.handle_resume_training(callback)

    service.get_or_create_current_question.assert_not_awaited()
    callback.message.answer.assert_awaited_once_with(training.TRAINING_RESUME_NO_ACTIVE_TEXT)


@pytest.mark.asyncio
async def test_handle_start_new_training_forces_new_session_from_active_preferences(monkeypatch) -> None:
    db = FakeDb()
    service = AsyncMock()
    service.get_active_session.return_value = SimpleNamespace(id=10, level="A1", theme="T01")
    service.get_or_create_current_question.return_value = _question()
    _patch_service(monkeypatch, service, db)

    callback = _Callback(data="train:new:10")

    await training.handle_start_new_training(callback)

    service.start_session.assert_awaited_once_with(
        db,
        111,
        level="A1",
        theme="T01",
        total_questions=5,
        force_new=True,
    )
    service.get_or_create_current_question.assert_awaited_once_with(db, 111, force_refresh=True)
    assert db.committed == 1
    assert TRAINING_QUESTION_TEMPLATE.format(position=1, total=3, question_text="Was ist korrekt?") in _extract_text(
        callback.message.answer.await_args
    )


@pytest.mark.asyncio
async def test_handle_start_new_training_rolls_back_daily_limit(monkeypatch) -> None:
    db = FakeDb()
    service = AsyncMock()
    service.get_active_session.return_value = SimpleNamespace(id=10, level="A1", theme="T01")
    service.start_session.side_effect = _daily_limit_error()
    _patch_service(monkeypatch, service, db)

    callback = _Callback(data="train:new:10")

    await training.handle_start_new_training(callback)

    assert db.rolled_back == 1
    assert PAYWALL_DAILY_LIMIT_TEXT == _extract_text(callback.message.answer.await_args)


@pytest.mark.asyncio
async def test_handle_cancel_training_reports_no_active_session(monkeypatch) -> None:
    db = FakeDb()
    service = AsyncMock()
    service.get_active_session.return_value = None
    _patch_service(monkeypatch, service, db)

    callback = _Callback(data="train:cancel:10")

    await training.handle_cancel_training(callback)

    service.cancel_active_session.assert_not_awaited()
    callback.message.answer.assert_awaited_once_with(training.TRAINING_RESUME_NO_ACTIVE_TEXT)


@pytest.mark.asyncio
async def test_handle_submit_answer_write_behind_uses_queue_and_update_id(monkeypatch) -> None:
    result = AnswerResult(
        selected_answer="a",
        correct_answer="a",
        question_token="tok12345",
        is_correct=True,
        is_duplicate=False,
        is_completed=False,
        explanation=None,
        correct_answers=1,
        total_questions=3,
        session_id=10,
    )
    accept = AsyncMock(return_value=result)
    monkeypatch.setattr(training, "get_settings", lambda: _settings(write_behind=True))
    monkeypatch.setattr(training, "_get_answer_persistence_queue", lambda: "queue")
    monkeypatch.setattr(training, "accept_answer_write_behind", accept)

    callback = _Callback(data="train:ans:10:tok12345:a")
    callback.id = "callback-1"

    await training.handle_submit_answer(callback, event_update=SimpleNamespace(update_id=777001))

    accept.assert_awaited_once_with(
        queue="queue",
        telegram_user_id=111,
        session_id=10,
        question_token="tok12345",
        selected_option_id="a",
        telegram_update_id=777001,
        callback_query_id=callback.id,
    )
    callback.message.answer.assert_awaited_once()


@pytest.mark.asyncio
async def test_handle_submit_answer_write_behind_maps_state_errors(monkeypatch) -> None:
    accept = AsyncMock(side_effect=ActiveSessionNotFoundError())
    monkeypatch.setattr(training, "get_settings", lambda: _settings(write_behind=True))
    monkeypatch.setattr(training, "_get_answer_persistence_queue", lambda: "queue")
    monkeypatch.setattr(training, "accept_answer_write_behind", accept)

    callback = _Callback(data="train:ans:10:tok12345:a")
    callback.id = "callback-1"

    await training.handle_submit_answer(callback)

    callback.message.answer.assert_awaited_once()
    assert training.TRAINING_SESSION_COMPLETED_TEXT in _extract_text(callback.message.answer.await_args)


def _settings(*, write_behind: bool = False):
    return SimpleNamespace(training_answer_write_behind_enabled=write_behind)
