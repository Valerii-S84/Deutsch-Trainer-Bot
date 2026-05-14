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
    assert models.User is not None
    assert models.QuizSession is not None
    assert models.UserAnswer is not None
    assert models.Progress is not None
    assert models.Mistake is not None
    assert models.Subscription is not None
    assert models.Payment is not None
    assert models.AnalyticsEvent is not None


def test_metadata_contains_expected_tables() -> None:
    expected = {
        "users",
        "quiz_sessions",
        "user_answers",
        "progress",
        "mistakes",
        "subscriptions",
        "payments",
        "analytics_events",
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
        "started_at",
        "finished_at",
        "total_questions",
        "correct_answers",
        "source",
    }
    assert expected.issubset(table.columns.keys())


def test_user_answers_columns_present() -> None:
    table = Base.metadata.tables["user_answers"]
    expected = {
        "session_id",
        "user_id",
        "external_quiz_id",
        "selected_answer",
        "correct_answer",
        "is_correct",
        "answered_at",
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
        "accuracy",
        "streak",
        "updated_at",
    }
    assert expected.issubset(table.columns.keys())


def test_mistakes_columns_present() -> None:
    table = Base.metadata.tables["mistakes"]
    expected = {
        "user_id",
        "external_quiz_id",
        "level",
        "theme",
        "wrong_answer",
        "correct_answer",
        "mistake_count",
        "last_seen_at",
        "resolved_at",
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
        "failed_at",
    }
    assert expected.issubset(table.columns.keys())


def test_analytics_columns_present() -> None:
    table = Base.metadata.tables["analytics_events"]
    expected = {"user_id", "event_name", "event_time", "event_metadata", "session_id", "source"}
    assert expected.issubset(table.columns.keys())


def test_required_indexes_and_constraints() -> None:
    assert _has_unique_constraint("users", {"telegram_user_id"})
    assert _has_unique_constraint("payments", {"idempotency_key"})
    assert _has_unique_constraint("payments", {"provider_payment_charge_id"})

    assert _has_index("users", ("telegram_user_id",), unique=True)
    assert _has_index("user_answers", ("user_id",))
    assert _has_index("user_answers", ("session_id",))
    assert _has_index("user_answers", ("external_quiz_id",))
    assert _has_index("mistakes", ("external_quiz_id",))
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
