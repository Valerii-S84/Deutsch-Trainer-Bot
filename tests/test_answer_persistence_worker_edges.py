from __future__ import annotations

import asyncio
from dataclasses import asdict
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from app.workers import answer_persistence
from app.workers.answer_persistence import (
    AnswerPersistenceQueueError,
    AnswerPersistenceWorker,
    _answer_ids_from_rows,
    _answer_identity,
    _answer_row,
    _missing_answer_events,
    _optional_dict,
    _optional_int,
    _optional_str,
    _outbox_payload,
    _parse_event,
    _required_bool,
    _required_int,
    _required_str,
)
from tests.test_answer_write_behind_pipeline import _persistable_event


@pytest.mark.asyncio
async def test_answer_persistence_worker_run_forever_retries_queue_errors(monkeypatch) -> None:
    queue = _QueueUnavailableOnce()
    worker = AnswerPersistenceWorker(queue=queue, batch_size=1)
    sleeps: list[float] = []

    async def sleep(delay: float) -> None:
        sleeps.append(delay)
        if len(sleeps) == 2:
            raise asyncio.CancelledError

    monkeypatch.setattr(answer_persistence.asyncio, "sleep", sleep)

    with pytest.raises(asyncio.CancelledError):
        await worker.run_forever(idle_sleep_seconds=0.01)

    assert sleeps == [1.0, 0.01]


def test_parse_event_validates_required_fields_and_keeps_optional_metadata() -> None:
    event = _persistable_event()
    payload = asdict(event)
    parsed = _parse_event(payload, answer_event_id="")

    assert parsed.answer_event_id == event.answer_event_id
    assert parsed.telegram_update_id == event.telegram_update_id
    assert parsed.metadata_snapshot == event.metadata_snapshot
    assert parsed.available_items_count == event.available_items_count

    invalid = dict(payload)
    invalid["telegram_user_id"] = "700001"
    with pytest.raises(ValueError, match="must be int"):
        _parse_event(invalid, answer_event_id="update:9001")


def test_answer_rows_and_outbox_payload_preserve_persistence_contract() -> None:
    event = _persistable_event()
    answered_at = datetime(2026, 7, 1, 10, tzinfo=UTC)

    answer_row = _answer_row(event, answered_at=answered_at)
    outbox_payload = _outbox_payload(event, answer_id=99, answered_at=answered_at)

    assert answer_row["telegram_update_id"] == 9001
    assert answer_row["quiz_source"] == "local_quiz_catalog"
    assert answer_row["training_session_item_id"] == 11
    assert outbox_payload["answer_id"] == 99
    assert outbox_payload["answered_at"] == answered_at.isoformat()
    assert outbox_payload["session_completed"] is False


def test_answer_id_resolution_prefers_telegram_update_id_then_identity() -> None:
    first = _persistable_event()
    second = _persistable_event().__class__(
        **{
            **asdict(_persistable_event()),
            "answer_event_id": "manual:q2",
            "telegram_update_id": None,
            "item_id": "q2",
        }
    )
    rows = [
        {"id": 10, "telegram_update_id": 9001, "session_id": 1, "user_id": 1, "external_quiz_id": "q1"},
        {"id": 11, "telegram_update_id": None, "session_id": 1, "user_id": 1, "external_quiz_id": "q2"},
    ]

    answer_ids = _answer_ids_from_rows(rows, [first, second])

    assert answer_ids == {"update:9001": 10, "manual:q2": 11}
    assert _missing_answer_events([first, second], {"update:9001": 10}) == [second]
    assert _answer_identity(second) == (1, 1, "q2")


def test_answer_persistence_field_helpers_reject_wrong_types() -> None:
    payload = {
        "int_value": 1,
        "str_value": "value",
        "bool_value": True,
        "dict_value": {"ok": True},
        "empty": "",
    }

    assert _required_int(payload, "int_value") == 1
    assert _optional_int(payload, "missing") is None
    assert _required_str(payload, "str_value") == "value"
    assert _optional_str(payload, "empty") is None
    assert _required_bool(payload, "bool_value") is True
    assert _optional_dict(payload, "dict_value") == {"ok": True}

    with pytest.raises(ValueError, match="must be int"):
        _required_int(payload, "str_value")
    with pytest.raises(ValueError, match="non-empty string"):
        _required_str(payload, "empty")
    with pytest.raises(ValueError, match="must be bool"):
        _required_bool(payload, "int_value")


class _QueueUnavailableOnce:
    def __init__(self) -> None:
        self.calls = 0

    async def claim_stale(self, **_kwargs):
        self.calls += 1
        if self.calls == 1:
            raise AnswerPersistenceQueueError("redis down")
        return []

    async def read_batch(self, **_kwargs):
        return []
