from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.db.models.mistake import MistakeStatus
from app.services.progress_model import TopicAnswerEvent
from app.workers import outbox_batch
from app.workers.outbox_batch import (
    ClaimedAnswerEvent,
    MistakeState,
    PostgresOutboxBatchProcessor,
    _accuracy,
    _aggregate_topics,
    _apply_review_success,
    _as_aware_utc,
    _batch_trailing_correct_count,
    _berlin_date,
    _claimed_answer_event,
    _increment_wrong,
    _json_number,
    _later,
    _new_mistake_state,
    _number_delta,
    _progress_delta,
    _progress_snapshot,
    _reopen_mistake,
    _status_value,
    _trailing_correct_streak,
)
from app.workers.outbox_payloads import parse_answer_accepted_payload
from tests.test_outbox_worker import _answer_payload


@pytest.mark.asyncio
async def test_batch_processor_process_sorts_events_and_runs_side_effect_phases(monkeypatch) -> None:
    early = SimpleNamespace(
        id=2,
        event_type="answer.accepted",
        created_at=datetime(2026, 7, 1, 9, tzinfo=UTC),
        payload=_payload(answer_id=2, answered_at="2026-07-01T09:00:00+00:00"),
    )
    late = SimpleNamespace(
        id=1,
        event_type="answer.accepted",
        created_at=datetime(2026, 7, 1, 10, tzinfo=UTC),
        payload=_payload(answer_id=1, answered_at="2026-07-01T10:00:00+00:00"),
    )
    processor = PostgresOutboxBatchProcessor()
    calls: list[tuple[str, list[int]]] = []

    async def record_mistakes(_db, events):
        calls.append(("mistakes", [event.outbox_event_id for event in events]))

    async def record_progress(_db, events):
        calls.append(("progress", [event.outbox_event_id for event in events]))

    async def record_analytics(_db, events):
        calls.append(("analytics", [event.outbox_event_id for event in events]))

    monkeypatch.setattr(processor, "_apply_mistakes", record_mistakes)
    monkeypatch.setattr(processor, "_apply_progress", record_progress)
    monkeypatch.setattr(processor, "_insert_analytics", record_analytics)

    await processor.process(object(), [late, early])

    assert calls == [
        ("mistakes", [2, 1]),
        ("progress", [2, 1]),
        ("analytics", [2, 1]),
    ]


@pytest.mark.asyncio
async def test_batch_processor_applies_mistakes_for_new_repeat_reopen_and_review_success(monkeypatch) -> None:
    now = datetime(2026, 7, 1, 10, tzinfo=UTC)
    new_wrong = _event(1, _payload(item_id="q1", answer_id=1, is_correct=False), now)
    repeated_wrong = _event(2, _payload(item_id="q2", answer_id=2, is_correct=False), now + timedelta(minutes=1))
    reopened_wrong = _event(3, _payload(item_id="q3", answer_id=3, is_correct=False), now + timedelta(minutes=2))
    review_success = _event(
        4,
        _payload(item_id="q4", answer_id=4, is_correct=True, session_type="mistake_review"),
        now + timedelta(days=1),
    )
    existing_repeated = _mistake_state(item_id="q2", status=MistakeStatus.new.value, existed=True, id=22)
    existing_resolved = _mistake_state(
        item_id="q3",
        status=MistakeStatus.resolved.value,
        resolved_at=now - timedelta(days=1),
        existed=True,
        id=33,
    )
    existing_review = _mistake_state(
        item_id="q4",
        status=MistakeStatus.improved.value,
        successful_repeats_count=2,
        successful_repeat_days_count=1,
        last_successful_repeat_at=now - timedelta(days=1),
        existed=True,
        id=44,
    )

    async def load_latest(_db, _keys):
        return {
            (existing_repeated.user_id, existing_repeated.external_quiz_id): existing_repeated,
            (existing_resolved.user_id, existing_resolved.external_quiz_id): existing_resolved,
            (existing_review.user_id, existing_review.external_quiz_id): existing_review,
        }

    db = _BatchDbSpy(inserted_ids={(1, "q1"): 11})
    monkeypatch.setattr(outbox_batch, "_load_latest_mistakes", load_latest)

    await PostgresOutboxBatchProcessor()._apply_mistakes(
        db,
        [new_wrong, repeated_wrong, reopened_wrong, review_success],
    )

    assert existing_repeated.mistake_count == 2
    assert existing_resolved.resolved_at is None
    assert existing_review.status == MistakeStatus.resolved.value
    assert existing_review.resolved_at == review_success.answered_at
    assert any(row["external_quiz_id"] == "q1" for row in db.inserted_rows)
    assert len(db.history_rows) == 4
    assert {row["event_type"] for row in db.history_rows} == {
        "wrong_created",
        "wrong_repeated",
        "wrong_reopened",
        "review_resolved",
    }


@pytest.mark.asyncio
async def test_batch_processor_progress_updates_scores_and_history(monkeypatch) -> None:
    now = datetime(2026, 7, 1, 10, tzinfo=UTC)
    events = [
        _event(1, _payload(item_id="q1", answer_id=1, is_correct=False), now),
        _event(2, _payload(item_id="q2", answer_id=2, is_correct=True), now + timedelta(minutes=1)),
    ]
    progress = SimpleNamespace(
        id=10,
        user_id=1,
        level="A1",
        theme="Alltag",
        theme_key="old-key",
        total_answered=2,
        total_correct=1,
        wrong_count=1,
        available_items_count=10,
        last_answered_at=now,
        last_recalculated_at=now,
        accuracy=Decimal("50.00"),
        streak=0,
        unique_items_seen=1,
        coverage_score=10.0,
        coverage_status="low",
        stability_score=20.0,
        weakness_score=30.0,
        recency_score=40.0,
        topic_status="weak",
    )
    db = _BatchDbSpy()
    processor = PostgresOutboxBatchProcessor()
    upserted: list[dict[tuple[int, str, str | None], outbox_batch.TopicAggregate]] = []

    async def load_progress(_db, keys, *, for_update):
        assert for_update is True
        return {next(iter(keys)): progress}

    async def load_recent(_db, _keys):
        return {
            (1, "A1", "Alltag"): [
                TopicAnswerEvent("q0", False, now - timedelta(minutes=1), "regular"),
                TopicAnswerEvent("q1", True, now, "regular"),
                TopicAnswerEvent("q2", True, now + timedelta(minutes=1), "regular"),
            ]
        }

    async def load_unique(_db, _keys):
        return {(1, "A1", "Alltag"): 3}

    async def load_signals(_db, _keys):
        return {}

    async def upsert(_db, aggregates):
        upserted.append(aggregates)

    monkeypatch.setattr(outbox_batch, "_load_progress_rows", load_progress)
    monkeypatch.setattr(outbox_batch, "_load_recent_answer_events", load_recent)
    monkeypatch.setattr(outbox_batch, "_load_unique_item_counts", load_unique)
    monkeypatch.setattr(outbox_batch, "_load_mistake_signals", load_signals)
    monkeypatch.setattr(processor, "_upsert_progress_totals", upsert)

    await processor._apply_progress(db, events)

    assert upserted
    assert db.progress_update_rows[0]["streak"] == 2
    assert db.progress_update_rows[0]["accuracy"] == Decimal("50.00")
    assert db.progress_history_rows[0]["event_type"] == "answer_recorded"
    assert db.progress_history_rows[0]["delta"]["answered_delta"] == 0


@pytest.mark.asyncio
async def test_batch_processor_records_completion_analytics() -> None:
    repo = _AnalyticsRepoSpy()
    processor = PostgresOutboxBatchProcessor(analytics_repo=repo)
    event = _event(
        1,
        _payload(answer_id=1, is_correct=True, session_completed=True, answered_count=5, correct_answers=4),
        datetime(2026, 7, 1, 10, tzinfo=UTC),
    )

    await processor._insert_analytics(object(), [event])

    assert [row["event_name"] for row in repo.rows] == [
        "question_answered",
        "training_completed",
        "result_shown",
    ]
    assert repo.rows[0]["event_metadata"]["outbox_event_id"] == 1


def test_outbox_batch_helpers_preserve_answer_and_progress_semantics() -> None:
    first = _event(1, _payload(answer_id=1, is_correct=False), datetime(2026, 7, 1, 10, tzinfo=UTC))
    second = _event(2, _payload(answer_id=2, is_correct=True), datetime(2026, 7, 1, 11, tzinfo=UTC))

    aggregates = _aggregate_topics([first, second])
    aggregate = aggregates[(1, "A1", "Alltag")]

    assert first.topic_key == (1, "A1", "Alltag")
    assert first.mistake_key == (1, "q1")
    assert aggregate.answered_delta == 2
    assert aggregate.correct_delta == 1
    assert aggregate.wrong_delta == 1
    assert aggregate.last_wrong_at == first.answered_at
    assert aggregate.latest_event == second
    assert _batch_trailing_correct_count([first, second]) == 1
    assert _trailing_correct_streak(
        [
            TopicAnswerEvent("q1", False, first.answered_at, "regular"),
            TopicAnswerEvent("q2", True, second.answered_at, "regular"),
        ]
    ) == 1


def test_mistake_state_transitions_and_rows_are_consistent() -> None:
    wrong = _event(1, _payload(is_correct=False), datetime(2026, 7, 1, 10, tzinfo=UTC))
    repeat = _event(2, _payload(answer_id=2, selected_answer="a3", is_correct=False), wrong.answered_at + timedelta(hours=1))
    state = _new_mistake_state(wrong)

    _increment_wrong(state, repeat)
    assert state.mistake_count == 2
    assert state.wrong_answer == "a3"
    assert state.status == MistakeStatus.repeated.value

    state.resolved_at = repeat.answered_at
    _reopen_mistake(state, repeat)
    assert state.resolved_at is None
    assert state.status == MistakeStatus.repeated.value

    _apply_review_success(state, _event(3, _payload(answer_id=3, is_correct=True), repeat.answered_at + timedelta(days=1)))
    assert state.status == MistakeStatus.improved.value
    assert state.successful_repeats_count == 1


def test_progress_numeric_helpers_handle_empty_and_invalid_values() -> None:
    progress = SimpleNamespace(
        total_answered=4,
        total_correct=3,
        wrong_count=1,
        accuracy=Decimal("75.00"),
        coverage_score=Decimal("33.3"),
        coverage_status="partial",
        stability_score=None,
        weakness_score="bad",
        recency_score=5,
        unique_items_seen=2,
        available_items_count=10,
        topic_status="steady",
    )

    previous = _progress_snapshot(progress)
    new = _progress_snapshot(progress, {"total_answered": 6, "total_correct": 4, "wrong_count": 2, "unique_items_seen": 3})

    assert _accuracy(0, 0) == Decimal("0.00")
    assert _accuracy(2, 3) == Decimal("66.67")
    assert _progress_delta(previous, new)["answered_delta"] == 2
    assert _json_number("bad") is None
    assert _number_delta(None, 1) is None
    assert _number_delta("1.5", "3.0") == 1.5


def test_datetime_and_event_parsing_helpers_normalize_inputs() -> None:
    naive = datetime(2026, 7, 1, 10)
    aware = datetime(2026, 7, 1, 10, tzinfo=UTC)
    raw = SimpleNamespace(id=9, event_type="answer.accepted", created_at=naive, payload=_payload())

    claimed = _claimed_answer_event(raw)

    assert claimed.outbox_event_id == 9
    assert claimed.created_at.tzinfo is UTC
    assert _as_aware_utc(naive).tzinfo is UTC
    assert _berlin_date(aware).isoformat() == "2026-07-01"
    assert _later(None, aware) == aware
    assert _later(aware, aware + timedelta(seconds=1)) == aware + timedelta(seconds=1)
    assert _status_value(MistakeStatus.new) == "new"

    with pytest.raises(ValueError, match="Unsupported"):
        _claimed_answer_event(SimpleNamespace(id=1, event_type="other", created_at=aware, payload={}))


class _AnalyticsRepoSpy:
    def __init__(self) -> None:
        self.rows: list[dict[str, object]] = []

    async def record_many(self, _db, rows):
        self.rows.extend(rows)


class _BatchDbSpy:
    def __init__(self, *, inserted_ids: dict[tuple[int, str], int] | None = None) -> None:
        self._inserted_ids = inserted_ids or {}
        self.inserted_rows: list[dict[str, object]] = []
        self.history_rows: list[dict[str, object]] = []
        self.progress_update_rows: list[dict[str, object]] = []
        self.progress_history_rows: list[dict[str, object]] = []

    async def execute(self, _statement, rows=None):
        if rows:
            first = rows[0]
            if "external_quiz_id" in first:
                self.inserted_rows.extend(rows)
                return _InsertResult(
                    [
                        {
                            "id": self._inserted_ids[(row["user_id"], row["external_quiz_id"])],
                            "user_id": row["user_id"],
                            "external_quiz_id": row["external_quiz_id"],
                        }
                        for row in rows
                    ]
                )
            if "event_type" in first and "mistake_id" in first:
                self.history_rows.extend(rows)
            elif "reason_code" in first:
                self.progress_history_rows.extend(rows)
            elif "progress_id" in first:
                self.progress_update_rows.extend(rows)
        return _InsertResult([])


class _InsertResult:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self._rows = rows

    def mappings(self):
        return self

    def all(self):
        return self._rows


def _event(outbox_event_id: int, payload: dict[str, object], created_at: datetime) -> ClaimedAnswerEvent:
    return ClaimedAnswerEvent(
        outbox_event_id=outbox_event_id,
        created_at=created_at,
        payload=parse_answer_accepted_payload(payload),
    )


def _payload(**overrides: object) -> dict[str, object]:
    payload = _answer_payload()
    payload.update(overrides)
    return payload


def _mistake_state(
    *,
    item_id: str,
    status: str,
    id: int | None = None,
    existed: bool = False,
    resolved_at: datetime | None = None,
    successful_repeats_count: int = 0,
    successful_repeat_days_count: int = 0,
    last_successful_repeat_at: datetime | None = None,
) -> MistakeState:
    timestamp = datetime(2026, 7, 1, 9, tzinfo=UTC)
    return MistakeState(
        id=id,
        user_id=1,
        external_quiz_id=item_id,
        item_id=item_id,
        level="A1",
        theme="Alltag",
        theme_key="alltag",
        wrong_answer="a1",
        correct_answer="a2",
        mistake_count=1,
        successful_repeats_count=successful_repeats_count,
        successful_repeat_days_count=successful_repeat_days_count,
        last_seen_at=timestamp,
        first_mistake_at=timestamp,
        last_mistake_at=timestamp,
        last_repeated_at=timestamp,
        last_successful_repeat_at=last_successful_repeat_at,
        resolved_at=resolved_at,
        status=status,
        content_available=True,
        source_snapshot={"session_type": "regular"},
        existed=existed,
    )
