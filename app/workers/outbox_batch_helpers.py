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

from app.workers.outbox_batch import (
    ANSWER_ACCEPTED_EVENT,
    BERLIN_TZ,
    ClaimedAnswerEvent,
    MistakeHistoryPlan,
    MistakeKey,
    MistakeState,
    TopicAggregate,
    TopicKey,
)


def _claimed_answer_event(event: object) -> ClaimedAnswerEvent:
    payload = getattr(event, "payload", None)
    event_type = getattr(event, "event_type", None)
    if event_type != ANSWER_ACCEPTED_EVENT or not isinstance(payload, dict):
        raise ValueError(f"Unsupported outbox event type: {event_type}")
    return ClaimedAnswerEvent(
        outbox_event_id=int(getattr(event, "id")),
        created_at=_as_aware_utc(getattr(event, "created_at")),
        payload=parse_answer_accepted_payload(payload),
    )


def _aggregate_topics(events: list[ClaimedAnswerEvent]) -> dict[TopicKey, TopicAggregate]:
    aggregates: dict[TopicKey, TopicAggregate] = {}
    for event in events:
        key = event.topic_key
        aggregate = aggregates.get(key)
        if aggregate is None:
            aggregate = TopicAggregate(
                user_id=event.payload.user_id,
                level=event.payload.level,
                theme=event.payload.theme,
            )
            aggregates[key] = aggregate
        aggregate.theme_key = event.payload.theme_key or event.payload.theme_id or aggregate.theme_key
        aggregate.answered_delta += 1
        aggregate.correct_delta += 1 if event.payload.is_correct else 0
        aggregate.wrong_delta += 0 if event.payload.is_correct else 1
        aggregate.last_answered_at = _later(aggregate.last_answered_at, event.answered_at)
        if not event.payload.is_correct:
            aggregate.last_wrong_at = _later(aggregate.last_wrong_at, event.answered_at)
        if event.payload.available_items_count is not None:
            aggregate.available_items_count = event.payload.available_items_count
        aggregate.latest_event = event
        aggregate.events.append(event)
    return aggregates


async def _load_latest_mistakes(
    db: AsyncSession,
    keys: set[MistakeKey],
) -> dict[MistakeKey, MistakeState]:
    if not keys:
        return {}
    rank = func.row_number().over(
        partition_by=(Mistake.user_id, Mistake.external_quiz_id),
        order_by=(case((Mistake.resolved_at.is_(None), 0), else_=1), Mistake.id.desc()),
    ).label("row_rank")
    ranked = (
        select(Mistake.id.label("id"), rank)
        .where(_mistake_key_clause(keys))
        .subquery()
    )
    latest_ids = select(ranked.c.id).where(ranked.c.row_rank == 1)
    query = select(Mistake).where(Mistake.id.in_(latest_ids))
    rows = list((await db.scalars(query.with_for_update())).all())
    states: dict[MistakeKey, MistakeState] = {}
    for row in rows:
        state = MistakeState(
            id=int(row.id),
            user_id=int(row.user_id),
            external_quiz_id=str(row.external_quiz_id),
            item_id=str(row.item_id or row.external_quiz_id),
            level=str(row.level),
            theme=str(row.theme),
            theme_key=row.theme_key,
            wrong_answer=str(row.wrong_answer),
            correct_answer=str(row.correct_answer),
            mistake_count=int(row.mistake_count or 0),
            successful_repeats_count=int(row.successful_repeats_count or 0),
            successful_repeat_days_count=int(row.successful_repeat_days_count or 0),
            last_seen_at=_as_aware_utc(row.last_seen_at),
            first_mistake_at=_as_aware_utc(row.first_mistake_at),
            last_mistake_at=_as_aware_utc(row.last_mistake_at),
            last_repeated_at=_as_aware_utc(row.last_repeated_at) if row.last_repeated_at is not None else None,
            last_successful_repeat_at=_as_aware_utc(row.last_successful_repeat_at)
            if row.last_successful_repeat_at is not None
            else None,
            resolved_at=_as_aware_utc(row.resolved_at) if row.resolved_at is not None else None,
            status=_status_value(row.status),
            content_available=bool(row.content_available),
            source_snapshot=row.source_snapshot if isinstance(row.source_snapshot, dict) else None,
            existed=True,
        )
        states[(state.user_id, state.external_quiz_id)] = state
    return states


async def _load_progress_rows(
    db: AsyncSession,
    keys: set[TopicKey],
    *,
    for_update: bool,
) -> dict[TopicKey, Progress]:
    if not keys:
        return {}
    query = select(Progress).where(_topic_key_clause(keys, Progress.user_id, Progress.level, Progress.theme))
    if for_update:
        query = query.with_for_update()
    rows = list((await db.scalars(query)).all())
    return {
        (int(row.user_id), str(row.level), row.theme): row
        for row in rows
    }


async def _load_unique_item_counts(
    db: AsyncSession,
    keys: set[TopicKey],
) -> dict[TopicKey, int]:
    if not keys:
        return {}
    query = (
        select(
            UserAnswer.user_id,
            UserAnswer.level,
            UserAnswer.theme,
            func.count(func.distinct(UserAnswer.external_quiz_id)).label("unique_items"),
        )
        .where(_topic_key_clause(keys, UserAnswer.user_id, UserAnswer.level, UserAnswer.theme))
        .group_by(UserAnswer.user_id, UserAnswer.level, UserAnswer.theme)
    )
    rows = (await db.execute(query)).all()
    return {
        (int(row.user_id), str(row.level), row.theme): int(row.unique_items or 0)
        for row in rows
    }


async def _load_recent_answer_events(
    db: AsyncSession,
    keys: set[TopicKey],
) -> dict[TopicKey, list[TopicAnswerEvent]]:
    if not keys:
        return {}
    rank = func.row_number().over(
        partition_by=(UserAnswer.user_id, UserAnswer.level, UserAnswer.theme),
        order_by=(UserAnswer.answered_at.desc(), UserAnswer.id.desc()),
    ).label("row_rank")
    subquery = (
        select(
            UserAnswer.user_id.label("user_id"),
            UserAnswer.level.label("level"),
            UserAnswer.theme.label("theme"),
            UserAnswer.external_quiz_id.label("external_quiz_id"),
            UserAnswer.is_correct.label("is_correct"),
            UserAnswer.answered_at.label("answered_at"),
            UserAnswer.session_type.label("session_type"),
            rank,
        )
        .where(_topic_key_clause(keys, UserAnswer.user_id, UserAnswer.level, UserAnswer.theme))
        .subquery()
    )
    rows = (
        await db.execute(
            select(subquery).where(subquery.c.row_rank <= RECENT_TOPIC_EVENTS_LIMIT),
        )
    ).mappings().all()
    grouped: dict[TopicKey, list[TopicAnswerEvent]] = defaultdict(list)
    for row in rows:
        key = (int(row["user_id"]), str(row["level"]), row["theme"])
        grouped[key].append(
            TopicAnswerEvent(
                item_id=str(row["external_quiz_id"]),
                is_correct=bool(row["is_correct"]),
                answered_at=_as_aware_utc(row["answered_at"]),
                session_type=row["session_type"],
            ),
        )
    for key, events in grouped.items():
        events.sort(key=lambda item: item.answered_at)
    return grouped


async def _load_mistake_signals(
    db: AsyncSession,
    keys: set[TopicKey],
) -> dict[TopicKey, TopicMistakeSignals]:
    if not keys:
        return {}
    query = (
        select(
            Mistake.user_id,
            Mistake.level,
            Mistake.theme,
            Mistake.item_id,
            Mistake.external_quiz_id,
            Mistake.mistake_count,
        )
        .where(Mistake.resolved_at.is_(None))
        .where(_topic_key_clause(keys, Mistake.user_id, Mistake.level, Mistake.theme))
    )
    rows = (await db.execute(query)).all()
    grouped_rows: dict[TopicKey, list[object]] = defaultdict(list)
    for row in rows:
        key = (int(row.user_id), str(row.level), row.theme)
        grouped_rows[key].append(row)
    signals: dict[TopicKey, TopicMistakeSignals] = {}
    for key, items in grouped_rows.items():
        unresolved_item_ids = frozenset(str(item.item_id or item.external_quiz_id) for item in items)
        total_mistake_count = sum(max(0, int(item.mistake_count or 0)) for item in items)
        repeated_mistake_count = sum(max(0, int(item.mistake_count or 0) - 1) for item in items)
        signals[key] = TopicMistakeSignals(
            unresolved_count=len(items),
            total_mistake_count=total_mistake_count,
            repeated_mistake_count=repeated_mistake_count,
            unresolved_item_ids=unresolved_item_ids,
        )
    return signals


def _new_mistake_state(event: ClaimedAnswerEvent) -> MistakeState:
    payload = event.payload
    timestamp = event.answered_at
    return MistakeState(
        user_id=payload.user_id,
        external_quiz_id=payload.item_id,
        item_id=payload.item_id,
        level=payload.level,
        theme=payload.theme or "",
        theme_key=payload.theme_key or payload.theme_id,
        wrong_answer=payload.selected_answer,
        correct_answer=payload.correct_answer,
        mistake_count=1,
        successful_repeats_count=0,
        successful_repeat_days_count=0,
        last_seen_at=timestamp,
        first_mistake_at=timestamp,
        last_mistake_at=timestamp,
        last_repeated_at=timestamp,
        last_successful_repeat_at=None,
        resolved_at=None,
        status=MistakeStatus.new.value,
        content_available=True,
        source_snapshot=_mistake_source_snapshot(payload),
    )


def _increment_wrong(state: MistakeState, event: ClaimedAnswerEvent) -> None:
    payload = event.payload
    timestamp = event.answered_at
    state.item_id = payload.item_id
    state.level = payload.level
    state.theme = payload.theme or ""
    state.theme_key = payload.theme_key or payload.theme_id
    state.wrong_answer = payload.selected_answer
    state.correct_answer = payload.correct_answer
    state.mistake_count = max(0, int(state.mistake_count or 0)) + 1
    state.successful_repeats_count = 0
    state.successful_repeat_days_count = 0
    state.last_successful_repeat_at = None
    state.resolved_at = None
    state.status = MistakeStatus.repeated.value
    state.content_available = True
    state.source_snapshot = _mistake_source_snapshot(payload)
    state.last_seen_at = timestamp
    state.last_mistake_at = timestamp
    state.last_repeated_at = timestamp


def _reopen_mistake(state: MistakeState, event: ClaimedAnswerEvent) -> None:
    _increment_wrong(state, event)
    state.status = MistakeStatus.repeated.value


def _apply_review_success(state: MistakeState, event: ClaimedAnswerEvent) -> None:
    payload = event.payload
    timestamp = event.answered_at
    previous_success_day = _berlin_date(state.last_successful_repeat_at)
    current_success_day = _berlin_date(timestamp)
    state.successful_repeats_count = int(state.successful_repeats_count or 0) + 1
    if previous_success_day != current_success_day:
        state.successful_repeat_days_count = int(state.successful_repeat_days_count or 0) + 1
    state.correct_answer = payload.correct_answer
    state.last_successful_repeat_at = timestamp
    state.last_seen_at = timestamp
    state.content_available = True
    if (
        int(state.successful_repeats_count or 0) >= 3
        and int(state.successful_repeat_days_count or 0) >= 2
    ):
        state.status = MistakeStatus.resolved.value
        state.resolved_at = timestamp
        return
    state.status = MistakeStatus.improved.value
    state.resolved_at = None


def _mistake_insert_row(state: MistakeState) -> dict[str, object]:
    return {
        "user_id": state.user_id,
        "external_quiz_id": state.external_quiz_id,
        "item_id": state.item_id,
        "level": state.level,
        "theme": state.theme,
        "theme_key": state.theme_key,
        "wrong_answer": state.wrong_answer,
        "correct_answer": state.correct_answer,
        "mistake_count": state.mistake_count,
        "successful_repeats_count": state.successful_repeats_count,
        "successful_repeat_days_count": state.successful_repeat_days_count,
        "last_seen_at": state.last_seen_at,
        "first_mistake_at": state.first_mistake_at,
        "last_mistake_at": state.last_mistake_at,
        "last_repeated_at": state.last_repeated_at,
        "last_successful_repeat_at": state.last_successful_repeat_at,
        "resolved_at": state.resolved_at,
        "status": state.status,
        "content_available": state.content_available,
        "source_snapshot": state.source_snapshot,
    }


def _mistake_update_row(state: MistakeState) -> dict[str, object]:
    return {
        "mistake_id": state.id,
        "item_id": state.item_id,
        "level": state.level,
        "theme": state.theme,
        "theme_key": state.theme_key,
        "wrong_answer": state.wrong_answer,
        "correct_answer": state.correct_answer,
        "mistake_count": state.mistake_count,
        "successful_repeats_count": state.successful_repeats_count,
        "successful_repeat_days_count": state.successful_repeat_days_count,
        "last_seen_at": state.last_seen_at,
        "first_mistake_at": state.first_mistake_at,
        "last_mistake_at": state.last_mistake_at,
        "last_repeated_at": state.last_repeated_at,
        "last_successful_repeat_at": state.last_successful_repeat_at,
        "resolved_at": state.resolved_at,
        "status": state.status,
        "content_available": state.content_available,
        "source_snapshot": state.source_snapshot,
    }


def _mistake_source_snapshot(payload: AnswerAcceptedPayload) -> dict[str, object]:
    return {
        "session_type": payload.session_type,
        "question_token": payload.question_token,
        "metadata_snapshot": payload.metadata_snapshot,
    }


def _topic_key_clause(keys: set[TopicKey], user_column, level_column, theme_column):
    clauses = []
    for user_id, level, theme in keys:
        clause = and_(user_column == user_id, level_column == level)
        if theme is None:
            clause = and_(clause, theme_column.is_(None))
        else:
            clause = and_(clause, theme_column == theme)
        clauses.append(clause)
    return or_(*clauses)


def _mistake_key_clause(keys: set[MistakeKey]):
    return or_(
        *(
            and_(Mistake.user_id == user_id, Mistake.external_quiz_id == item_id)
            for user_id, item_id in keys
        ),
    )


def _progress_snapshot(progress: Progress, override: dict[str, object] | None = None) -> dict[str, object]:
    data = {
        "total_answered": int(progress.total_answered or 0),
        "total_correct": int(progress.total_correct or 0),
        "wrong_count": int(progress.wrong_count or 0),
        "accuracy": _json_number(progress.accuracy),
        "coverage_score": _json_number(progress.coverage_score),
        "coverage_status": progress.coverage_status,
        "stability_score": _json_number(progress.stability_score),
        "weakness_score": _json_number(progress.weakness_score),
        "recency_score": _json_number(progress.recency_score),
        "unique_items_seen": int(progress.unique_items_seen or 0),
        "available_items_count": progress.available_items_count,
        "topic_status": progress.topic_status,
    }
    if override is not None:
        for key, value in override.items():
            if key == "progress_id" or key == "last_recalculated_at":
                continue
            data[key] = _json_number(value) if key.endswith("_score") or key == "accuracy" else value
    return data


def _progress_delta(previous: dict[str, object] | None, new: dict[str, object]) -> dict[str, object] | None:
    if previous is None:
        return None
    return {
        "answered_delta": int(new["total_answered"]) - int(previous["total_answered"]),
        "correct_delta": int(new["total_correct"]) - int(previous["total_correct"]),
        "wrong_delta": int(new["wrong_count"]) - int(previous["wrong_count"]),
        "unique_items_seen_delta": int(new["unique_items_seen"]) - int(previous["unique_items_seen"]),
        "accuracy_delta": _number_delta(previous.get("accuracy"), new.get("accuracy")),
        "coverage_delta": _number_delta(previous.get("coverage_score"), new.get("coverage_score")),
        "stability_delta": _number_delta(previous.get("stability_score"), new.get("stability_score")),
        "weakness_delta": _number_delta(previous.get("weakness_score"), new.get("weakness_score")),
    }


def _accuracy(total_correct: int | None, total_answered: int | None) -> Decimal:
    answered = int(total_answered or 0)
    correct = int(total_correct or 0)
    if answered <= 0:
        return Decimal("0.00")
    value = (Decimal(correct) * Decimal("100")) / Decimal(answered)
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _trailing_correct_streak(events: list[TopicAnswerEvent]) -> int:
    streak = 0
    for event in reversed(events):
        if not event.is_correct:
            break
        streak += 1
    return streak


def _batch_trailing_correct_count(events: list[ClaimedAnswerEvent]) -> int:
    streak = 0
    for event in reversed(events):
        if not event.payload.is_correct:
            break
        streak += 1
    return streak


def _greatest_nullable(existing, incoming):
    return case(
        (existing.is_(None), incoming),
        (incoming.is_(None), existing),
        else_=func.greatest(existing, incoming),
    )


def _later(current: datetime | None, candidate: datetime | None) -> datetime | None:
    if current is None:
        return candidate
    if candidate is None:
        return current
    return max(current, candidate)


def _as_aware_utc(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(UTC)
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _berlin_date(value: datetime | None) -> date | None:
    if value is None:
        return None
    return _as_aware_utc(value).astimezone(BERLIN_TZ).date()


def _json_number(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _number_delta(previous_value: object, new_value: object) -> float | None:
    previous = _json_number(previous_value)
    current = _json_number(new_value)
    if previous is None or current is None:
        return None
    return round(current - previous, 2)


def _status_value(status: object) -> str:
    return str(status.value if hasattr(status, "value") else status)
