from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal, ROUND_HALF_UP
from zoneinfo import ZoneInfo

from sqlalchemy import and_, bindparam, case, func, insert, or_, select, update
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Mistake, MistakeHistory, Progress, ProgressHistory, UserAnswer
from app.db.models.mistake import MistakeStatus
from app.repositories.analytics_events import AnalyticsEventRepository
from app.runtime.timing import timing_span
from app.services.progress import RECENT_TOPIC_EVENTS_LIMIT
from app.services.progress_model import TopicAnswerEvent, TopicMistakeSignals, calculate_topic_scores
from app.workers.outbox_payloads import AnswerAcceptedPayload, parse_answer_accepted_payload

TopicKey = tuple[int, str, str | None]
MistakeKey = tuple[int, str]

ANSWER_ACCEPTED_EVENT = "answer.accepted"
BERLIN_TZ = ZoneInfo("Europe/Berlin")


@dataclass(frozen=True)
class ClaimedAnswerEvent:
    outbox_event_id: int
    created_at: datetime
    payload: AnswerAcceptedPayload

    @property
    def answered_at(self) -> datetime:
        return self.payload.answered_at or self.created_at

    @property
    def topic_key(self) -> TopicKey:
        return (self.payload.user_id, self.payload.level, self.payload.theme)

    @property
    def mistake_key(self) -> MistakeKey:
        return (self.payload.user_id, self.payload.item_id)


@dataclass
class TopicAggregate:
    user_id: int
    level: str
    theme: str | None
    theme_key: str | None = None
    answered_delta: int = 0
    correct_delta: int = 0
    wrong_delta: int = 0
    last_answered_at: datetime | None = None
    last_wrong_at: datetime | None = None
    available_items_count: int | None = None
    latest_event: ClaimedAnswerEvent | None = None
    events: list[ClaimedAnswerEvent] = field(default_factory=list)


@dataclass
class MistakeState:
    user_id: int
    external_quiz_id: str
    item_id: str
    level: str
    theme: str
    theme_key: str | None
    wrong_answer: str
    correct_answer: str
    mistake_count: int
    successful_repeats_count: int
    successful_repeat_days_count: int
    last_seen_at: datetime
    first_mistake_at: datetime
    last_mistake_at: datetime
    last_repeated_at: datetime | None
    last_successful_repeat_at: datetime | None
    resolved_at: datetime | None
    status: str
    content_available: bool
    source_snapshot: dict[str, object] | None
    id: int | None = None
    existed: bool = False


@dataclass(frozen=True)
class MistakeHistoryPlan:
    key: MistakeKey
    event: ClaimedAnswerEvent
    event_type: str
    previous_status: str | None
    wrong_answer: str | None = None
    correct_answer: str | None = None
    metadata_snapshot: dict[str, object] | None = None


@dataclass(frozen=True)
class ProgressBatchInputs:
    aggregates: dict[TopicKey, TopicAggregate]
    recent_events: dict[TopicKey, list[TopicAnswerEvent]]
    unique_items: dict[TopicKey, int]
    mistake_signals: dict[TopicKey, TopicMistakeSignals]
    previous_scores: dict[TopicKey, dict[str, object]]
    previous_status: dict[TopicKey, str | None]


class _PostgresMistakeBatchProcessor:
    def __init__(self, *, analytics_repo: AnalyticsEventRepository | None = None) -> None:
        self._analytics_repo = analytics_repo or AnalyticsEventRepository()

    async def process(self, db: AsyncSession, events: list[object]) -> None:
        claimed = [_claimed_answer_event(event) for event in events]
        claimed.sort(key=lambda item: (item.answered_at, item.outbox_event_id))
        with timing_span("worker.mistake_ms"):
            await self._apply_mistakes(db, claimed)
        with timing_span("worker.progress_ms"):
            await self._apply_progress(db, claimed)
        with timing_span("worker.analytics_ms"):
            await self._insert_analytics(db, claimed)

    async def _apply_mistakes(self, db: AsyncSession, events: list[ClaimedAnswerEvent]) -> None:
        relevant = [
            event
            for event in events
            if not event.payload.is_correct or event.payload.session_type == "mistake_review"
        ]
        if not relevant:
            return

        states = await _load_latest_mistakes(db, {event.mistake_key for event in relevant})
        plans, new_keys = self._plan_mistake_changes(relevant, states)
        await self._insert_new_mistakes(db, states, new_keys)
        await self._update_existing_mistakes(db, states)
        await self._insert_mistake_history(db, states, plans)

    def _plan_mistake_changes(
        self,
        events: list[ClaimedAnswerEvent],
        states: dict[MistakeKey, MistakeState],
    ) -> tuple[list[MistakeHistoryPlan], list[MistakeKey]]:
        plans: list[MistakeHistoryPlan] = []
        new_keys: list[MistakeKey] = []
        for event in events:
            key = event.mistake_key
            state = states.get(key)
            updated, plan, is_new = self._plan_mistake_event(event, state)
            if updated is None or plan is None:
                continue
            states[key] = updated
            plans.append(plan)
            if is_new:
                new_keys.append(key)
        return plans, new_keys

    def _plan_mistake_event(
        self,
        event: ClaimedAnswerEvent,
        state: MistakeState | None,
    ) -> tuple[MistakeState | None, MistakeHistoryPlan | None, bool]:
        if event.payload.is_correct:
            return self._plan_review_success(event, state)
        return self._plan_wrong_answer(event, state)

    @staticmethod
    def _plan_review_success(
        event: ClaimedAnswerEvent,
        state: MistakeState | None,
    ) -> tuple[MistakeState | None, MistakeHistoryPlan | None, bool]:
        payload = event.payload
        if payload.session_type != "mistake_review" or state is None or state.resolved_at is not None:
            return state, None, False
        previous_status = state.status
        _apply_review_success(state, event)
        event_type = "review_resolved" if state.status == MistakeStatus.resolved.value else "review_improved"
        plan = MistakeHistoryPlan(
            key=event.mistake_key,
            event=event,
            event_type=event_type,
            previous_status=previous_status,
            correct_answer=payload.correct_answer,
            metadata_snapshot=payload.metadata_snapshot,
        )
        return state, plan, False

    @staticmethod
    def _plan_wrong_answer(
        event: ClaimedAnswerEvent,
        state: MistakeState | None,
    ) -> tuple[MistakeState, MistakeHistoryPlan, bool]:
        payload = event.payload
        is_new = state is None
        previous_status = None if state is None else state.status
        if state is None:
            state = _new_mistake_state(event)
            event_type = "wrong_created"
        elif state.resolved_at is not None:
            _reopen_mistake(state, event)
            event_type = "wrong_reopened"
        else:
            _increment_wrong(state, event)
            event_type = "wrong_repeated"
        plan = MistakeHistoryPlan(
            key=event.mistake_key,
            event=event,
            event_type=event_type,
            previous_status=previous_status,
            wrong_answer=payload.selected_answer,
            correct_answer=payload.correct_answer,
            metadata_snapshot=payload.metadata_snapshot,
        )
        return state, plan, is_new

    @staticmethod
    async def _insert_new_mistakes(
        db: AsyncSession,
        states: dict[MistakeKey, MistakeState],
        new_keys: list[MistakeKey],
    ) -> None:
        if new_keys:
            rows = [_mistake_insert_row(states[key]) for key in new_keys]
            inserted = (
                await db.execute(
                    insert(Mistake).returning(Mistake.id, Mistake.user_id, Mistake.external_quiz_id),
                    rows,
                )
            ).mappings().all()
            for row in inserted:
                key = (int(row["user_id"]), str(row["external_quiz_id"]))
                states[key].id = int(row["id"])

    @staticmethod
    async def _update_existing_mistakes(
        db: AsyncSession,
        states: dict[MistakeKey, MistakeState],
    ) -> None:
        update_rows = [
            _mistake_update_row(state)
            for state in states.values()
            if state.id is not None and state.existed
        ]
        if update_rows:
            await db.execute(
                update(Mistake.__table__)
                .where(Mistake.__table__.c.id == bindparam("mistake_id"))
                .values(
                    item_id=bindparam("item_id"),
                    level=bindparam("level"),
                    theme=bindparam("theme"),
                    theme_key=bindparam("theme_key"),
                    wrong_answer=bindparam("wrong_answer"),
                    correct_answer=bindparam("correct_answer"),
                    mistake_count=bindparam("mistake_count"),
                    successful_repeats_count=bindparam("successful_repeats_count"),
                    successful_repeat_days_count=bindparam("successful_repeat_days_count"),
                    last_seen_at=bindparam("last_seen_at"),
                    first_mistake_at=bindparam("first_mistake_at"),
                    last_mistake_at=bindparam("last_mistake_at"),
                    last_repeated_at=bindparam("last_repeated_at"),
                    last_successful_repeat_at=bindparam("last_successful_repeat_at"),
                    resolved_at=bindparam("resolved_at"),
                    status=bindparam("status"),
                    content_available=bindparam("content_available"),
                    source_snapshot=bindparam("source_snapshot"),
                ),
                update_rows,
            )

    @staticmethod
    async def _insert_mistake_history(
        db: AsyncSession,
        states: dict[MistakeKey, MistakeState],
        plans: list[MistakeHistoryPlan],
    ) -> None:
        history_rows = [
            {
                "mistake_id": states[plan.key].id,
                "user_id": plan.event.payload.user_id,
                "user_answer_id": plan.event.payload.answer_id,
                "session_id": plan.event.payload.session_id,
                "item_id": plan.event.payload.item_id,
                "event_type": plan.event_type,
                "previous_status": plan.previous_status,
                "new_status": states[plan.key].status,
                "wrong_answer": plan.wrong_answer,
                "correct_answer": plan.correct_answer,
                "metadata_snapshot": plan.metadata_snapshot,
            }
            for plan in plans
            if states[plan.key].id is not None
        ]
        if history_rows:
            await db.execute(insert(MistakeHistory), history_rows)

class PostgresOutboxBatchProcessor(_PostgresMistakeBatchProcessor):
    async def _apply_progress(self, db: AsyncSession, events: list[ClaimedAnswerEvent]) -> None:
        if not events:
            return

        aggregates = _aggregate_topics(events)
        topic_keys = set(aggregates)
        previous_rows = await _load_progress_rows(db, topic_keys, for_update=True)
        previous_scores = {key: _progress_snapshot(row) for key, row in previous_rows.items()}
        previous_status = {key: row.topic_status for key, row in previous_rows.items()}

        await self._upsert_progress_totals(db, aggregates)

        current_rows = await _load_progress_rows(db, topic_keys, for_update=True)
        inputs = ProgressBatchInputs(
            aggregates=aggregates,
            recent_events=await _load_recent_answer_events(db, topic_keys),
            unique_items=await _load_unique_item_counts(db, topic_keys),
            mistake_signals=await _load_mistake_signals(db, topic_keys),
            previous_scores=previous_scores,
            previous_status=previous_status,
        )
        update_rows, history_rows = self._progress_change_rows(current_rows, inputs)
        await self._write_progress_changes(db, update_rows, history_rows)

    def _progress_change_rows(
        self,
        current_rows: dict[TopicKey, Progress],
        inputs: ProgressBatchInputs,
    ) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
        update_rows: list[dict[str, object]] = []
        history_rows: list[dict[str, object]] = []
        for key, progress in current_rows.items():
            update_row, history_row = self._progress_change_row(key, progress, inputs)
            update_rows.append(update_row)
            history_rows.append(history_row)
        return update_rows, history_rows

    @staticmethod
    def _progress_change_row(
        key: TopicKey,
        progress: Progress,
        inputs: ProgressBatchInputs,
    ) -> tuple[dict[str, object], dict[str, object]]:
        aggregate = inputs.aggregates[key]
        topic_events = inputs.recent_events.get(key, [])
        unique_items_seen = inputs.unique_items.get(key, 0)
        scores = calculate_topic_scores(
            total_answered=int(progress.total_answered or 0),
            accuracy_score=_accuracy(progress.total_correct, progress.total_answered),
            unique_items_seen=unique_items_seen,
            available_items_count=progress.available_items_count,
            last_answered_at=progress.last_answered_at,
            answer_events=topic_events,
            mistake_signals=inputs.mistake_signals.get(key, TopicMistakeSignals()),
            now=aggregate.last_answered_at,
        )
        update_row = _progress_update_row(progress, aggregate, scores, topic_events, unique_items_seen)
        new_scores = _progress_snapshot(progress, update_row)
        history_row = _progress_history_row(
            progress,
            aggregate,
            scores.topic_status,
            inputs.previous_scores.get(key),
            inputs.previous_status.get(key),
            new_scores,
        )
        return update_row, history_row

    @staticmethod
    async def _write_progress_changes(
        db: AsyncSession,
        update_rows: list[dict[str, object]],
        history_rows: list[dict[str, object]],
    ) -> None:
        if update_rows:
            await db.execute(
                update(Progress.__table__)
                .where(Progress.__table__.c.id == bindparam("progress_id"))
                .values(
                    theme_key=bindparam("theme_key"),
                    available_items_count=bindparam("available_items_count"),
                    accuracy=bindparam("accuracy"),
                    streak=bindparam("streak"),
                    unique_items_seen=bindparam("unique_items_seen"),
                    coverage_score=bindparam("coverage_score"),
                    coverage_status=bindparam("coverage_status"),
                    stability_score=bindparam("stability_score"),
                    weakness_score=bindparam("weakness_score"),
                    recency_score=bindparam("recency_score"),
                    topic_status=bindparam("topic_status"),
                    last_recalculated_at=bindparam("last_recalculated_at"),
                ),
                update_rows,
            )
        if history_rows:
            await db.execute(insert(ProgressHistory), history_rows)

    async def _upsert_progress_totals(
        self,
        db: AsyncSession,
        aggregates: dict[TopicKey, TopicAggregate],
    ) -> None:
        rows = [
            {
                "user_id": aggregate.user_id,
                "level": aggregate.level,
                "theme": aggregate.theme,
                "theme_key": aggregate.theme_key,
                "total_answered": aggregate.answered_delta,
                "total_correct": aggregate.correct_delta,
                "wrong_count": aggregate.wrong_delta,
                "available_items_count": aggregate.available_items_count,
                "last_answered_at": aggregate.last_answered_at,
                "last_wrong_at": aggregate.last_wrong_at,
                "streak": _batch_trailing_correct_count(aggregate.events),
                "last_recalculated_at": aggregate.last_answered_at,
            }
            for aggregate in aggregates.values()
        ]
        if not rows:
            return

        statement = postgresql_insert(Progress).values(rows)
        excluded = statement.excluded
        await db.execute(
            statement.on_conflict_do_update(
                index_elements=[Progress.user_id, Progress.level, Progress.theme],
                set_={
                    "theme_key": func.coalesce(excluded.theme_key, Progress.theme_key),
                    "total_answered": Progress.total_answered + excluded.total_answered,
                    "total_correct": Progress.total_correct + excluded.total_correct,
                    "wrong_count": Progress.wrong_count + excluded.wrong_count,
                    "available_items_count": func.coalesce(excluded.available_items_count, Progress.available_items_count),
                    "last_answered_at": _greatest_nullable(Progress.last_answered_at, excluded.last_answered_at),
                    "last_wrong_at": _greatest_nullable(Progress.last_wrong_at, excluded.last_wrong_at),
                },
            ),
        )

    async def _insert_analytics(self, db: AsyncSession, events: list[ClaimedAnswerEvent]) -> None:
        analytics_rows: list[dict[str, object]] = []
        for event in events:
            payload = event.payload
            answer_metadata = {
                "answer_id": payload.answer_id,
                "outbox_event_id": event.outbox_event_id,
                "session_type": payload.session_type,
                "level": payload.level,
                "theme": payload.theme,
                "theme_id": payload.theme_id,
                "catalog_id": payload.catalog_id,
                "item_id": payload.item_id,
                "item_version": payload.item_version,
                "is_correct": payload.is_correct,
                "position": payload.position,
            }
            analytics_rows.append(
                {
                    "event_name": "question_answered",
                    "user_id": payload.user_id,
                    "session_id": payload.session_id,
                    "event_metadata": answer_metadata,
                    "source": "training",
                },
            )
            if not payload.session_completed:
                continue
            completion_metadata = {
                "answer_id": payload.answer_id,
                "outbox_event_id": event.outbox_event_id,
                "session_type": payload.session_type,
                "level": payload.level,
                "theme": payload.theme,
                "answered_count": payload.answered_count,
                "correct_answers": payload.correct_answers,
                "planned_question_count": payload.total_questions,
            }
            analytics_rows.extend(
                [
                    {
                        "event_name": "training_completed",
                        "user_id": payload.user_id,
                        "session_id": payload.session_id,
                        "event_metadata": completion_metadata,
                        "source": "training",
                    },
                    {
                        "event_name": "result_shown",
                        "user_id": payload.user_id,
                        "session_id": payload.session_id,
                        "event_metadata": completion_metadata,
                        "source": "training",
                    },
                ],
            )
        await self._analytics_repo.record_many(db, analytics_rows)


def _progress_update_row(
    progress: Progress,
    aggregate: TopicAggregate,
    scores,
    topic_events: list[TopicAnswerEvent],
    unique_items_seen: int,
) -> dict[str, object]:
    return {
        "progress_id": progress.id,
        "theme_key": aggregate.theme_key or progress.theme_key,
        "available_items_count": progress.available_items_count,
        "accuracy": _accuracy(progress.total_correct, progress.total_answered),
        "streak": _trailing_correct_streak(topic_events),
        "unique_items_seen": unique_items_seen,
        "coverage_score": scores.coverage_score,
        "coverage_status": scores.coverage_status,
        "stability_score": scores.stability_score,
        "weakness_score": scores.weakness_score,
        "recency_score": scores.recency_score,
        "topic_status": scores.topic_status,
        "last_recalculated_at": aggregate.last_answered_at or progress.last_recalculated_at,
    }


def _progress_history_row(
    progress: Progress,
    aggregate: TopicAggregate,
    new_status: str,
    previous_scores: dict[str, object] | None,
    previous_status: str | None,
    new_scores: dict[str, object],
) -> dict[str, object]:
    latest = aggregate.latest_event
    return {
        "progress_id": progress.id,
        "user_id": progress.user_id,
        "session_id": latest.payload.session_id if latest is not None else None,
        "user_answer_id": latest.payload.answer_id if latest is not None else None,
        "level": progress.level,
        "theme": progress.theme,
        "event_type": "answer_recorded",
        "previous_status": previous_status,
        "new_status": new_status,
        "previous_scores": previous_scores,
        "new_scores": new_scores,
        "delta": _progress_delta(previous_scores, new_scores),
        "reason_code": "answer_accepted_batch",
    }


from app.workers.outbox_batch_helpers import (
    _claimed_answer_event,
    _aggregate_topics,
    _load_latest_mistakes,
    _load_progress_rows,
    _load_unique_item_counts,
    _load_recent_answer_events,
    _load_mistake_signals,
    _new_mistake_state,
    _increment_wrong,
    _reopen_mistake,
    _apply_review_success,
    _mistake_insert_row,
    _mistake_update_row,
    _mistake_source_snapshot,
    _topic_key_clause,
    _mistake_key_clause,
    _progress_snapshot,
    _progress_delta,
    _accuracy,
    _trailing_correct_streak,
    _batch_trailing_correct_count,
    _greatest_nullable,
    _later,
    _as_aware_utc,
    _berlin_date,
    _json_number,
    _number_delta,
    _status_value,
)
