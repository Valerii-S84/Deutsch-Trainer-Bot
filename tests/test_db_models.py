from __future__ import annotations

from pathlib import Path

from sqlalchemy import Index, UniqueConstraint

from app.db.base import Base
from app.db import models  # noqa: F401


def _has_unique_constraint(table_name: str, expected_columns: set[str]) -> bool:
    table = Base.metadata.tables[table_name]
    return any(
        isinstance(constraint, UniqueConstraint) and set(constraint.columns.keys()) == expected_columns
        for constraint in table.constraints
    )


def _has_index(table_name: str, expected_columns: tuple[str, ...], unique: bool | None = None) -> bool:
    table = Base.metadata.tables[table_name]
    for index in table.indexes:
        if tuple(index.columns.keys()) == expected_columns:
            if unique is None:
                return True
            return index.unique == unique
    return False


def test_models_importable() -> None:
    assert models.ApiErrorLog is not None
    assert models.User is not None
    assert models.QuizSession is not None
    assert models.QuestionReference is not None
    assert models.TrainingSessionItem is not None
    assert models.UserAnswer is not None
    assert models.Progress is not None
    assert models.ProgressHistory is not None
    assert models.Mistake is not None
    assert models.MistakeHistory is not None
    assert models.DailyLimit is not None
    assert models.Recommendation is not None
    assert models.Subscription is not None
    assert models.Payment is not None
    assert models.AnalyticsEvent is not None


def test_metadata_contains_expected_tables() -> None:
    expected = {
        "users",
        "quiz_sessions",
        "question_references",
        "training_session_items",
        "user_answers",
        "progress",
        "progress_history",
        "mistakes",
        "mistake_history",
        "recommendations",
        "daily_limits",
        "subscriptions",
        "payments",
        "analytics_events",
        "api_error_logs",
    }
    assert expected.issubset(set(Base.metadata.tables))


def test_users_columns_present() -> None:
    table = Base.metadata.tables["users"]
    expected = {"telegram_user_id", "username", "first_name", "created_at", "updated_at", "is_blocked"}
    assert expected.issubset(table.columns.keys())


def test_quiz_sessions_columns_present() -> None:
    table = Base.metadata.tables["quiz_sessions"]
    expected = {
        "user_id",
        "level",
        "theme",
        "status",
        "session_type",
        "started_at",
        "finished_at",
        "completed_at",
        "abandoned_at",
        "failed_at",
        "total_questions",
        "shown_questions_count",
        "answered_count",
        "correct_answers",
        "source",
    }
    assert expected.issubset(table.columns.keys())


def test_question_references_columns_present() -> None:
    table = Base.metadata.tables["question_references"]
    expected = {
        "item_id",
        "level",
        "theme",
        "theme_key",
        "source",
        "metadata_snapshot",
        "content_version",
        "fetched_at",
    }
    assert expected.issubset(table.columns.keys())


def test_training_session_items_columns_present() -> None:
    table = Base.metadata.tables["training_session_items"]
    expected = {
        "session_id",
        "user_id",
        "question_reference_id",
        "item_id",
        "position",
        "status",
        "shown_at",
        "answered_at",
        "daily_limit_id",
        "daily_limit_charged_at",
    }
    assert expected.issubset(table.columns.keys())


def test_user_answers_columns_present() -> None:
    table = Base.metadata.tables["user_answers"]
    expected = {
        "session_id",
        "user_id",
        "training_session_item_id",
        "question_reference_id",
        "external_quiz_id",
        "level",
        "theme",
        "selected_answer",
        "correct_answer",
        "is_correct",
        "answered_at",
        "session_type",
        "metadata_snapshot",
        "telegram_update_id",
    }
    assert expected.issubset(table.columns.keys())


def test_progress_columns_present() -> None:
    table = Base.metadata.tables["progress"]
    expected = {
        "user_id",
        "level",
        "theme",
        "total_answered",
        "total_correct",
        "wrong_count",
        "accuracy",
        "coverage_score",
        "coverage_status",
        "stability_score",
        "weakness_score",
        "recency_score",
        "topic_status",
        "streak",
        "unique_items_seen",
        "available_items_count",
        "last_wrong_at",
        "last_recalculated_at",
        "updated_at",
    }
    assert expected.issubset(table.columns.keys())


def test_progress_history_columns_present() -> None:
    table = Base.metadata.tables["progress_history"]
    expected = {
        "progress_id",
        "user_id",
        "session_id",
        "user_answer_id",
        "level",
        "theme",
        "event_type",
        "new_status",
        "new_scores",
        "reason_code",
        "created_at",
    }
    assert expected.issubset(table.columns.keys())


def test_mistakes_columns_present() -> None:
    table = Base.metadata.tables["mistakes"]
    expected = {
        "user_id",
        "question_reference_id",
        "item_id",
        "external_quiz_id",
        "level",
        "theme",
        "wrong_answer",
        "correct_answer",
        "mistake_count",
        "successful_repeats_count",
        "successful_repeat_days_count",
        "last_seen_at",
        "first_mistake_at",
        "last_mistake_at",
        "last_successful_repeat_at",
        "resolved_at",
        "content_available",
    }
    assert expected.issubset(table.columns.keys())


def test_mistake_history_columns_present() -> None:
    table = Base.metadata.tables["mistake_history"]
    expected = {
        "mistake_id",
        "user_id",
        "user_answer_id",
        "session_id",
        "item_id",
        "event_type",
        "previous_status",
        "new_status",
        "metadata_snapshot",
        "created_at",
    }
    assert expected.issubset(table.columns.keys())


def test_daily_limits_columns_present() -> None:
    table = Base.metadata.tables["daily_limits"]
    expected = {
        "user_id",
        "plan",
        "limit_date",
        "timezone",
        "question_limit",
        "questions_used",
        "reset_at",
    }
    assert expected.issubset(table.columns.keys())


def test_recommendations_columns_present() -> None:
    table = Base.metadata.tables["recommendations"]
    expected = {
        "user_id",
        "level",
        "theme",
        "recommendation_type",
        "reason_code",
        "priority",
        "copy_de",
        "source_snapshot",
        "shown_at",
        "acted_at",
    }
    assert expected.issubset(table.columns.keys())


def test_subscriptions_columns_present() -> None:
    table = Base.metadata.tables["subscriptions"]
    expected = {"user_id", "plan", "status", "started_at", "expires_at", "source", "created_at", "updated_at"}
    assert expected.issubset(table.columns.keys())


def test_payments_columns_present() -> None:
    table = Base.metadata.tables["payments"]
    expected = {
        "user_id",
        "telegram_payment_charge_id",
        "plan",
        "amount_stars",
        "status",
        "idempotency_key",
        "created_at",
        "paid_at",
        "credited_at",
        "failed_at",
        "cancelled_at",
    }
    assert expected.issubset(table.columns.keys())


def test_analytics_columns_present() -> None:
    table = Base.metadata.tables["analytics_events"]
    expected = {"user_id", "event_name", "event_time", "event_metadata", "session_id", "source"}
    assert expected.issubset(table.columns.keys())


def test_api_error_log_columns_present() -> None:
    table = Base.metadata.tables["api_error_logs"]
    expected = {
        "user_id",
        "session_id",
        "request_id",
        "endpoint",
        "status_code",
        "error_category",
        "level",
        "theme",
        "metadata",
        "occurred_at",
        "created_at",
    }
    assert expected.issubset(table.columns.keys())


def test_required_indexes_and_constraints() -> None:
    assert _has_unique_constraint("users", {"telegram_user_id"})
    assert _has_unique_constraint("question_references", {"item_id"})
    assert _has_unique_constraint("training_session_items", {"session_id", "position"})
    assert _has_unique_constraint("training_session_items", {"session_id", "item_id"})
    assert _has_unique_constraint("daily_limits", {"user_id", "limit_date", "plan"})
    assert _has_unique_constraint("user_answers", {"telegram_update_id"})
    assert _has_unique_constraint("payments", {"idempotency_key"})
    assert _has_unique_constraint("payments", {"provider_payment_charge_id"})

    assert _has_index("users", ("telegram_user_id",), unique=True)
    assert _has_index("quiz_sessions", ("user_id", "status"))
    assert _has_index("question_references", ("level", "theme"))
    assert _has_index("training_session_items", ("session_id", "status"))
    assert _has_index("daily_limits", ("user_id", "limit_date"))
    assert _has_index("user_answers", ("user_id",))
    assert _has_index("user_answers", ("session_id",))
    assert _has_index("user_answers", ("training_session_item_id",))
    assert _has_index("user_answers", ("question_reference_id",))
    assert _has_index("user_answers", ("external_quiz_id",))
    assert _has_index("progress_history", ("user_id", "created_at"))
    assert _has_index("mistakes", ("external_quiz_id",))
    assert _has_index("mistake_history", ("user_id", "created_at"))
    assert _has_index("recommendations", ("user_id", "priority"))
    assert _has_index("api_error_logs", ("error_category",))
    assert _has_index("analytics_events", ("event_name", "event_time"))
    assert _has_index("subscriptions", ("status", "expires_at"))
    assert _has_unique_constraint("payments", {"idempotency_key"})
    assert _has_index("quiz_sessions", ("user_id",))  # session ownership lookup


def test_no_secrets_in_model_metadata_columns() -> None:
    secret_terms = {"secret", "token", "api_key", "api-key", "password"}
    for table in Base.metadata.tables.values():
        for column in table.columns:
            lower = column.name.lower()
            assert not any(term in lower for term in secret_terms), f"Potential secret-like column in {table.name}: {column.name}"


def test_no_real_secrets_in_env_example() -> None:
    env_example = Path(__file__).resolve().parents[1] / ".env.example"
    content = env_example.read_text(encoding="utf-8").lower()
    assert "postgres-password" in content
    assert "<" in content and ">" in content
    assert "real" not in content
