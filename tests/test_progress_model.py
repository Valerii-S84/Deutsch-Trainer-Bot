from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace

from app.services.progress_model import (
    CONFIDENCE_HIGH,
    TopicAnswerEvent,
    TopicMistakeSignals,
    build_progress_recommendation,
    calculate_topic_scores,
    determine_topic_status,
    recency_risk_score,
    stability_from_answers,
)


def test_high_accuracy_alone_does_not_make_topic_strong() -> None:
    status = determine_topic_status(
        total_answered=15,
        accuracy_score=Decimal("100.00"),
        coverage_score=Decimal("5.00"),
        stability_score=Decimal("100.00"),
        weakness_score=Decimal("0.00"),
        accuracy_confidence=CONFIDENCE_HIGH,
        stability_confidence_value=CONFIDENCE_HIGH,
        unresolved_mistake_count=0,
    )

    assert status == "new"


def test_coverage_unknown_blocks_strong_topic_status() -> None:
    status = determine_topic_status(
        total_answered=20,
        accuracy_score=Decimal("95.00"),
        coverage_score=None,
        stability_score=Decimal("90.00"),
        weakness_score=Decimal("5.00"),
        accuracy_confidence=CONFIDENCE_HIGH,
        stability_confidence_value=CONFIDENCE_HIGH,
        unresolved_mistake_count=0,
    )

    assert status != "strong"


def test_weakness_overrides_positive_signals() -> None:
    status = determine_topic_status(
        total_answered=20,
        accuracy_score=Decimal("95.00"),
        coverage_score=Decimal("80.00"),
        stability_score=Decimal("90.00"),
        weakness_score=Decimal("65.00"),
        accuracy_confidence=CONFIDENCE_HIGH,
        stability_confidence_value=CONFIDENCE_HIGH,
        unresolved_mistake_count=0,
    )

    assert status == "weak"


def test_recency_uses_europe_berlin_day_boundary() -> None:
    last_practice = datetime(2026, 5, 14, 21, 30, tzinfo=UTC)
    now = datetime(2026, 5, 14, 22, 30, tzinfo=UTC)

    assert recency_risk_score(last_practice, now=now) == Decimal("10.00")


def test_stability_uses_europe_berlin_days() -> None:
    events = [
        TopicAnswerEvent("q1", True, datetime(2026, 5, 14, 21, 30, tzinfo=UTC)),
        TopicAnswerEvent("q1", True, datetime(2026, 5, 14, 22, 30, tzinfo=UTC)),
    ]

    stability_score, confidence = stability_from_answers(events)

    assert stability_score == Decimal("75.00")
    assert confidence == "low"


def test_unresolved_mistake_caps_item_stability_until_resolved() -> None:
    events = [
        TopicAnswerEvent("q1", True, datetime(2026, 5, 14, 10, 0, tzinfo=UTC)),
        TopicAnswerEvent("q1", True, datetime(2026, 5, 15, 10, 0, tzinfo=UTC)),
    ]

    unresolved_score, _ = stability_from_answers(events, unresolved_item_ids={"q1"})
    resolved_score, _ = stability_from_answers(events, unresolved_item_ids=set())

    assert unresolved_score == Decimal("10.00")
    assert resolved_score == Decimal("75.00")


def test_calculate_topic_scores_marks_repeated_mistakes_as_weak() -> None:
    scores = calculate_topic_scores(
        total_answered=15,
        accuracy_score=Decimal("90.00"),
        unique_items_seen=10,
        available_items_count=10,
        last_answered_at=datetime(2026, 5, 14, 10, 0, tzinfo=UTC),
        answer_events=[
            TopicAnswerEvent("q1", True, datetime(2026, 5, 14, 10, 0, tzinfo=UTC)),
        ],
        mistake_signals=TopicMistakeSignals(
            unresolved_count=10,
            total_mistake_count=10,
            repeated_mistake_count=10,
            unresolved_item_ids=frozenset({"q1", "q2", "q3"}),
        ),
        now=datetime(2026, 5, 14, 10, 0, tzinfo=UTC),
    )

    assert scores.topic_status == "weak"
    assert scores.weakness_score >= Decimal("60.00")


def test_progress_recommendation_copy_is_german_for_weak_topic() -> None:
    record = SimpleNamespace(
        level="A2",
        theme="Dativ",
        weakness_score=Decimal("70.00"),
        recency_score=Decimal("0.00"),
        stability_score=Decimal("50.00"),
        coverage_score=Decimal("50.00"),
        total_answered=10,
    )

    recommendation = build_progress_recommendation([record])

    assert recommendation.recommendation_type == "practice_weak_topic"
    assert recommendation.copy_de == "Übe Dativ auf Niveau A2; dieses Thema braucht jetzt die meiste Aufmerksamkeit."
