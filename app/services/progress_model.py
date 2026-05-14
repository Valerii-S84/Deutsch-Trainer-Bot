from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Iterable
from zoneinfo import ZoneInfo


BERLIN_TZ = ZoneInfo("Europe/Berlin")

CONFIDENCE_NONE = "none"
CONFIDENCE_LOW = "low"
CONFIDENCE_MEDIUM = "medium"
CONFIDENCE_HIGH = "high"

TOPIC_STATUS_NEW = "new"
TOPIC_STATUS_WEAK = "weak"
TOPIC_STATUS_LEARNING = "learning"
TOPIC_STATUS_STABLE = "stable"
TOPIC_STATUS_STRONG = "strong"

COVERAGE_STATUS_KNOWN = "known"
COVERAGE_STATUS_UNKNOWN = "unknown"


@dataclass(frozen=True)
class TopicAnswerEvent:
    item_id: str
    is_correct: bool
    answered_at: datetime
    session_type: str | None = None


@dataclass(frozen=True)
class TopicMistakeSignals:
    unresolved_count: int = 0
    total_mistake_count: int = 0
    repeated_mistake_count: int = 0
    unresolved_item_ids: frozenset[str] = frozenset()


@dataclass(frozen=True)
class TopicScores:
    coverage_score: Decimal | None
    coverage_status: str
    stability_score: Decimal
    stability_confidence: str
    weakness_score: Decimal
    recency_score: Decimal
    topic_status: str


@dataclass(frozen=True)
class ProgressRecommendation:
    recommendation_type: str
    reason_code: str
    copy_de: str
    target_level: str | None = None
    target_theme: str | None = None


def answer_confidence(answered_count: int) -> str:
    if answered_count <= 0:
        return CONFIDENCE_NONE
    if answered_count <= 4:
        return CONFIDENCE_LOW
    if answered_count <= 14:
        return CONFIDENCE_MEDIUM
    return CONFIDENCE_HIGH


def coverage_from_counts(
    unique_items_seen: int,
    available_items_count: int | None,
) -> tuple[Decimal | None, str]:
    if available_items_count is None or available_items_count <= 0:
        return None, COVERAGE_STATUS_UNKNOWN
    raw_score = Decimal(max(0, unique_items_seen)) * Decimal("100") / Decimal(available_items_count)
    return _percent(min(raw_score, Decimal("100"))), COVERAGE_STATUS_KNOWN


def recency_risk_score(last_practiced_at: datetime | None, *, now: datetime | None = None) -> Decimal:
    if last_practiced_at is None:
        return Decimal("100.00")

    today = _berlin_date(now or datetime.now(UTC))
    last_practice_date = _berlin_date(last_practiced_at)
    days_since_last_practice = max(0, (today - last_practice_date).days)
    if days_since_last_practice == 0:
        return Decimal("0.00")
    if days_since_last_practice == 1:
        return Decimal("10.00")
    if days_since_last_practice == 2:
        return Decimal("20.00")
    if days_since_last_practice == 3:
        return Decimal("35.00")
    if days_since_last_practice <= 6:
        return Decimal("50.00")
    if days_since_last_practice <= 13:
        return Decimal("70.00")
    return Decimal("90.00")


def stability_from_answers(
    answer_events: Iterable[TopicAnswerEvent],
    *,
    unresolved_item_ids: set[str] | frozenset[str] | None = None,
) -> tuple[Decimal, str]:
    item_events: dict[str, list[TopicAnswerEvent]] = defaultdict(list)
    for event in answer_events:
        item_events[event.item_id].append(event)

    unresolved_ids = unresolved_item_ids or frozenset()
    eligible_scores: list[Decimal] = []
    for item_id, events in item_events.items():
        event_dates = {_berlin_date(event.answered_at) for event in events}
        if len(event_dates) < 2:
            continue
        eligible_scores.append(_item_stability_score(item_id, events, unresolved_ids))

    if not eligible_scores:
        return Decimal("0.00"), CONFIDENCE_NONE

    score = sum(eligible_scores, Decimal("0")) / Decimal(len(eligible_scores))
    return _percent(score), stability_confidence(len(eligible_scores))


def stability_confidence(eligible_item_count: int) -> str:
    if eligible_item_count <= 0:
        return CONFIDENCE_NONE
    if eligible_item_count <= 2:
        return CONFIDENCE_LOW
    if eligible_item_count <= 7:
        return CONFIDENCE_MEDIUM
    return CONFIDENCE_HIGH


def weakness_from_signals(
    *,
    total_answered: int,
    accuracy_score: Decimal,
    unique_items_seen: int,
    stability_score: Decimal,
    recency_score: Decimal,
    mistake_signals: TopicMistakeSignals,
) -> Decimal:
    if total_answered <= 0:
        return Decimal("0.00")

    error_component = Decimal("1") - (accuracy_score / Decimal("100"))
    repeat_mistake_component = Decimal(mistake_signals.repeated_mistake_count) / Decimal(
        max(mistake_signals.total_mistake_count, 1),
    )
    unresolved_mistake_component = Decimal(mistake_signals.unresolved_count) / Decimal(max(unique_items_seen, 1))
    instability_component = Decimal("1") - (stability_score / Decimal("100"))
    recency_risk_component = recency_score / Decimal("100")

    weakness_raw = (
        Decimal("0.30") * _unit_interval(error_component)
        + Decimal("0.25") * _unit_interval(unresolved_mistake_component)
        + Decimal("0.20") * _unit_interval(repeat_mistake_component)
        + Decimal("0.15") * _unit_interval(instability_component)
        + Decimal("0.10") * _unit_interval(recency_risk_component)
    )
    return _percent(weakness_raw * Decimal("100"))


def determine_topic_status(
    *,
    total_answered: int,
    accuracy_score: Decimal,
    coverage_score: Decimal | None,
    stability_score: Decimal,
    weakness_score: Decimal,
    accuracy_confidence: str,
    stability_confidence_value: str,
    unresolved_mistake_count: int,
) -> str:
    if total_answered < 5 or coverage_score is None or coverage_score < Decimal("10"):
        return TOPIC_STATUS_NEW
    if weakness_score >= Decimal("60") or accuracy_score < Decimal("60") or unresolved_mistake_count >= 3:
        return TOPIC_STATUS_WEAK
    if (
        accuracy_score >= Decimal("85")
        and coverage_score >= Decimal("70")
        and stability_score >= Decimal("75")
        and weakness_score < Decimal("25")
        and accuracy_confidence == CONFIDENCE_HIGH
        and stability_confidence_value == CONFIDENCE_HIGH
    ):
        return TOPIC_STATUS_STRONG
    if (
        accuracy_score >= Decimal("75")
        and coverage_score >= Decimal("40")
        and stability_score >= Decimal("60")
        and weakness_score < Decimal("40")
    ):
        return TOPIC_STATUS_STABLE
    if accuracy_score >= Decimal("60") and coverage_score >= Decimal("10"):
        return TOPIC_STATUS_LEARNING
    return TOPIC_STATUS_NEW


def calculate_topic_scores(
    *,
    total_answered: int,
    accuracy_score: Decimal,
    unique_items_seen: int,
    available_items_count: int | None,
    last_answered_at: datetime | None,
    answer_events: Iterable[TopicAnswerEvent],
    mistake_signals: TopicMistakeSignals,
    now: datetime | None = None,
) -> TopicScores:
    coverage_score, coverage_status = coverage_from_counts(unique_items_seen, available_items_count)
    stability_score, stability_confidence_value = stability_from_answers(
        answer_events,
        unresolved_item_ids=mistake_signals.unresolved_item_ids,
    )
    recency_score = recency_risk_score(last_answered_at, now=now)
    weakness_score = weakness_from_signals(
        total_answered=total_answered,
        accuracy_score=accuracy_score,
        unique_items_seen=unique_items_seen,
        stability_score=stability_score,
        recency_score=recency_score,
        mistake_signals=mistake_signals,
    )
    status = determine_topic_status(
        total_answered=total_answered,
        accuracy_score=accuracy_score,
        coverage_score=coverage_score,
        stability_score=stability_score,
        weakness_score=weakness_score,
        accuracy_confidence=answer_confidence(total_answered),
        stability_confidence_value=stability_confidence_value,
        unresolved_mistake_count=mistake_signals.unresolved_count,
    )
    return TopicScores(
        coverage_score=coverage_score,
        coverage_status=coverage_status,
        stability_score=stability_score,
        stability_confidence=stability_confidence_value,
        weakness_score=weakness_score,
        recency_score=recency_score,
        topic_status=status,
    )


def build_progress_recommendation(progress_records: Iterable[object]) -> ProgressRecommendation:
    records = list(progress_records)
    if not records:
        return ProgressRecommendation(
            recommendation_type="continue_learning",
            reason_code="insufficient_data",
            copy_de="Ich brauche noch ein paar Antworten, um eine gute Empfehlung zu geben. Starte eine kurze Übung.",
        )

    weak_record = _highest(records, "weakness_score", minimum=Decimal("60"))
    if weak_record is not None:
        return _recommend(
            weak_record,
            recommendation_type="practice_weak_topic",
            reason_code="weakness_threshold",
            copy_de="Übe {theme} auf Niveau {level}; dieses Thema braucht jetzt die meiste Aufmerksamkeit.",
        )

    stale_record = _stale_unstable_record(records)
    if stale_record is not None:
        return _recommend(
            stale_record,
            recommendation_type="restore_recency",
            reason_code="recency_risk",
            copy_de="Wiederhole {theme} auf Niveau {level}; das Thema wurde länger nicht geübt.",
        )

    low_coverage_record = _lowest_coverage_record(records)
    if low_coverage_record is not None:
        return _recommend(
            low_coverage_record,
            recommendation_type="increase_coverage",
            reason_code="low_coverage",
            copy_de="Bearbeite weitere Fragen zu {theme} auf Niveau {level}, damit dein Fortschritt belastbarer wird.",
        )

    return ProgressRecommendation(
        recommendation_type="continue_learning",
        reason_code="continue_learning",
        copy_de="Mach mit einer kurzen Übung weiter, um deinen Fortschritt zu festigen.",
    )


def _item_stability_score(
    item_id: str,
    events: list[TopicAnswerEvent],
    unresolved_item_ids: set[str] | frozenset[str],
) -> Decimal:
    ordered_events = sorted(events, key=lambda event: _as_aware_utc(event.answered_at))
    latest_event = ordered_events[-1]
    if not latest_event.is_correct:
        return Decimal("0")
    if item_id in unresolved_item_ids:
        return Decimal("10")

    correct_dates = sorted({_berlin_date(event.answered_at) for event in ordered_events if event.is_correct})
    if not correct_dates:
        return Decimal("0")

    if len(correct_dates) >= 3 and (correct_dates[-1] - correct_dates[0]).days >= 7:
        return Decimal("100")
    if len(correct_dates) >= 3:
        return Decimal("90")
    if len(correct_dates) == 2:
        return Decimal("75")
    return Decimal("55")


def _berlin_date(value: datetime) -> date:
    return _as_aware_utc(value).astimezone(BERLIN_TZ).date()


def _as_aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _percent(value: Decimal) -> Decimal:
    return min(max(value, Decimal("0")), Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _unit_interval(value: Decimal) -> Decimal:
    return min(max(value, Decimal("0")), Decimal("1"))


def _decimal_attr(record: object, name: str) -> Decimal:
    value = getattr(record, name, None)
    if value is None:
        return Decimal("0")
    return Decimal(str(value))


def _highest(records: list[object], field_name: str, *, minimum: Decimal) -> object | None:
    candidates = [record for record in records if _decimal_attr(record, field_name) >= minimum]
    if not candidates:
        return None
    return max(candidates, key=lambda record: _decimal_attr(record, field_name))


def _stale_unstable_record(records: list[object]) -> object | None:
    candidates = [
        record
        for record in records
        if _decimal_attr(record, "recency_score") >= Decimal("70")
        and _decimal_attr(record, "stability_score") < Decimal("75")
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda record: _decimal_attr(record, "recency_score"))


def _lowest_coverage_record(records: list[object]) -> object | None:
    candidates = [
        record
        for record in records
        if getattr(record, "coverage_score", None) is not None
        and _decimal_attr(record, "coverage_score") < Decimal("40")
        and int(getattr(record, "total_answered", 0) or 0) >= 5
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda record: _decimal_attr(record, "coverage_score"))


def _recommend(
    record: object,
    *,
    recommendation_type: str,
    reason_code: str,
    copy_de: str,
) -> ProgressRecommendation:
    level = str(getattr(record, "level", "") or "")
    theme = str(getattr(record, "theme", "") or "")
    return ProgressRecommendation(
        recommendation_type=recommendation_type,
        reason_code=reason_code,
        target_level=level or None,
        target_theme=theme or None,
        copy_de=copy_de.format(level=level or "deinem Niveau", theme=theme or "deinem Thema"),
    )
