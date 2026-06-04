"""Extend milestone 2 schema with session item and history tables."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "202605140002"
down_revision = "202605140001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "quiz_sessions",
        sa.Column("session_type", sa.String(length=32), nullable=False, server_default=sa.text("'regular'")),
    )
    op.add_column("quiz_sessions", sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("quiz_sessions", sa.Column("abandoned_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("quiz_sessions", sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "quiz_sessions",
        sa.Column("shown_questions_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "quiz_sessions",
        sa.Column("answered_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index("ix_quiz_sessions_user_status", "quiz_sessions", ["user_id", "status"])
    op.create_check_constraint(
        "ck_quiz_sessions_shown_count_non_negative",
        "quiz_sessions",
        "shown_questions_count >= 0",
    )
    op.create_check_constraint(
        "ck_quiz_sessions_answered_count_non_negative",
        "quiz_sessions",
        "answered_count >= 0",
    )
    op.create_check_constraint(
        "ck_quiz_sessions_answered_count_lte_total",
        "quiz_sessions",
        "answered_count <= total_questions",
    )

    op.create_table(
        "question_references",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("item_id", sa.String(length=255), nullable=False),
        sa.Column("level", sa.String(length=8), nullable=False),
        sa.Column("theme", sa.String(length=255), nullable=False),
        sa.Column("theme_key", sa.String(length=255), nullable=True),
        sa.Column("source", sa.String(length=64), nullable=False, server_default=sa.text("'quiz_bank_api'")),
        sa.Column("metadata_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("content_version", sa.String(length=128), nullable=True),
        sa.Column("question_text_snapshot", sa.Text(), nullable=True),
        sa.Column("correct_answer_snapshot", sa.Text(), nullable=True),
        sa.Column("explanation_snapshot", sa.Text(), nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("item_id", name="uq_question_references_item_id"),
        sa.CheckConstraint("level IN ('A1', 'A2', 'B1', 'B2', 'C1')", name="ck_question_references_supported_level"),
    )
    op.create_index("ix_question_references_level_theme", "question_references", ["level", "theme"])
    op.create_index("ix_question_references_theme_key", "question_references", ["theme_key"])

    op.create_table(
        "daily_limits",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("plan", sa.String(length=16), nullable=False),
        sa.Column("limit_date", sa.Date(), nullable=False),
        sa.Column("timezone", sa.String(length=64), nullable=False, server_default=sa.text("'Europe/Berlin'")),
        sa.Column("question_limit", sa.Integer(), nullable=False),
        sa.Column("questions_used", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("reset_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("user_id", "limit_date", "plan", name="uq_daily_limits_user_date_plan"),
        sa.CheckConstraint("question_limit >= 0", name="ck_daily_limits_question_limit_non_negative"),
        sa.CheckConstraint("questions_used >= 0", name="ck_daily_limits_questions_used_non_negative"),
        sa.CheckConstraint("questions_used <= question_limit", name="ck_daily_limits_questions_used_lte_limit"),
    )
    op.create_index("ix_daily_limits_user_date", "daily_limits", ["user_id", "limit_date"])

    op.create_table(
        "training_session_items",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("session_id", sa.BigInteger(), sa.ForeignKey("quiz_sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "question_reference_id",
            sa.BigInteger(),
            sa.ForeignKey("question_references.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("item_id", sa.String(length=255), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default=sa.text("'prepared'")),
        sa.Column("shown_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("answered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("daily_limit_id", sa.BigInteger(), sa.ForeignKey("daily_limits.id", ondelete="SET NULL"), nullable=True),
        sa.Column("daily_limit_charged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("session_id", "position", name="uq_training_session_items_session_position"),
        sa.UniqueConstraint("session_id", "item_id", name="uq_training_session_items_session_item"),
        sa.CheckConstraint("position > 0", name="ck_training_session_items_position_positive"),
    )
    op.create_index("ix_training_session_items_user_id", "training_session_items", ["user_id"])
    op.create_index("ix_training_session_items_session_status", "training_session_items", ["session_id", "status"])
    op.create_index(
        "ix_training_session_items_question_reference_id",
        "training_session_items",
        ["question_reference_id"],
    )
    op.create_index("ix_training_session_items_daily_limit_id", "training_session_items", ["daily_limit_id"])

    op.add_column("user_answers", sa.Column("training_session_item_id", sa.BigInteger(), nullable=True))
    op.add_column("user_answers", sa.Column("question_reference_id", sa.BigInteger(), nullable=True))
    op.add_column("user_answers", sa.Column("level", sa.String(length=8), nullable=True))
    op.add_column("user_answers", sa.Column("theme", sa.String(length=255), nullable=True))
    op.add_column("user_answers", sa.Column("theme_key", sa.String(length=255), nullable=True))
    op.add_column(
        "user_answers",
        sa.Column("session_type", sa.String(length=32), nullable=False, server_default=sa.text("'regular'")),
    )
    op.add_column("user_answers", sa.Column("metadata_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column("user_answers", sa.Column("telegram_update_id", sa.BigInteger(), nullable=True))
    op.create_foreign_key(
        "fk_user_answers_training_session_item_id",
        "user_answers",
        "training_session_items",
        ["training_session_item_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_user_answers_question_reference_id",
        "user_answers",
        "question_references",
        ["question_reference_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_user_answers_training_session_item_id", "user_answers", ["training_session_item_id"])
    op.create_index("ix_user_answers_question_reference_id", "user_answers", ["question_reference_id"])
    op.create_index("ix_user_answers_level_theme", "user_answers", ["level", "theme"])
    op.create_unique_constraint("uq_user_answers_telegram_update_id", "user_answers", ["telegram_update_id"])

    op.add_column("progress", sa.Column("theme_key", sa.String(length=255), nullable=True))
    op.add_column("progress", sa.Column("wrong_count", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("progress", sa.Column("coverage_score", sa.Numeric(5, 2), nullable=True))
    op.add_column(
        "progress",
        sa.Column("coverage_status", sa.String(length=16), nullable=False, server_default=sa.text("'unknown'")),
    )
    op.add_column("progress", sa.Column("stability_score", sa.Numeric(5, 2), nullable=False, server_default="0"))
    op.add_column("progress", sa.Column("weakness_score", sa.Numeric(5, 2), nullable=False, server_default="0"))
    op.add_column("progress", sa.Column("recency_score", sa.Numeric(5, 2), nullable=True))
    op.add_column("progress", sa.Column("topic_status", sa.String(length=16), nullable=False, server_default=sa.text("'new'")))
    op.add_column("progress", sa.Column("unique_items_seen", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("progress", sa.Column("available_items_count", sa.Integer(), nullable=True))
    op.add_column("progress", sa.Column("last_wrong_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "progress",
        sa.Column("last_recalculated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_check_constraint("ck_progress_wrong_count_non_negative", "progress", "wrong_count >= 0")
    op.create_check_constraint(
        "ck_progress_counts_lte_answered",
        "progress",
        "total_correct + wrong_count <= total_answered",
    )
    op.create_check_constraint(
        "ck_progress_coverage_percent",
        "progress",
        "coverage_score IS NULL OR (coverage_score >= 0 AND coverage_score <= 100)",
    )
    op.create_check_constraint(
        "ck_progress_stability_percent",
        "progress",
        "stability_score >= 0 AND stability_score <= 100",
    )
    op.create_check_constraint(
        "ck_progress_weakness_percent",
        "progress",
        "weakness_score >= 0 AND weakness_score <= 100",
    )
    op.create_check_constraint(
        "ck_progress_recency_percent",
        "progress",
        "recency_score IS NULL OR (recency_score >= 0 AND recency_score <= 100)",
    )
    op.create_check_constraint("ck_progress_unique_items_non_negative", "progress", "unique_items_seen >= 0")
    op.create_check_constraint(
        "ck_progress_available_non_negative",
        "progress",
        "available_items_count IS NULL OR available_items_count >= 0",
    )

    op.add_column("mistakes", sa.Column("question_reference_id", sa.BigInteger(), nullable=True))
    op.add_column("mistakes", sa.Column("item_id", sa.String(length=255), nullable=True))
    op.add_column("mistakes", sa.Column("theme_key", sa.String(length=255), nullable=True))
    op.add_column("mistakes", sa.Column("successful_repeats_count", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("mistakes", sa.Column("successful_repeat_days_count", sa.Integer(), nullable=False, server_default="0"))
    op.add_column(
        "mistakes",
        sa.Column("first_mistake_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.add_column(
        "mistakes",
        sa.Column("last_mistake_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.add_column("mistakes", sa.Column("last_repeated_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("mistakes", sa.Column("last_successful_repeat_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("mistakes", sa.Column("content_available", sa.Boolean(), nullable=False, server_default=sa.text("true")))
    op.create_foreign_key(
        "fk_mistakes_question_reference_id",
        "mistakes",
        "question_references",
        ["question_reference_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_mistakes_question_reference_id", "mistakes", ["question_reference_id"])
    op.create_index("ix_mistakes_item_id", "mistakes", ["item_id"])
    op.create_check_constraint(
        "ck_mistakes_successful_repeats_non_negative",
        "mistakes",
        "successful_repeats_count >= 0",
    )
    op.create_check_constraint(
        "ck_mistakes_successful_repeat_days_non_negative",
        "mistakes",
        "successful_repeat_days_count >= 0",
    )

    op.add_column("payments", sa.Column("credited_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("payments", sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True))

    op.create_table(
        "progress_history",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("progress_id", sa.BigInteger(), sa.ForeignKey("progress.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("session_id", sa.BigInteger(), sa.ForeignKey("quiz_sessions.id", ondelete="SET NULL"), nullable=True),
        sa.Column("user_answer_id", sa.BigInteger(), sa.ForeignKey("user_answers.id", ondelete="SET NULL"), nullable=True),
        sa.Column("level", sa.String(length=8), nullable=False),
        sa.Column("theme", sa.String(length=255), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("previous_status", sa.String(length=32), nullable=True),
        sa.Column("new_status", sa.String(length=32), nullable=False),
        sa.Column("previous_scores", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("new_scores", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("delta", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("reason_code", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_progress_history_user_created", "progress_history", ["user_id", "created_at"])
    op.create_index("ix_progress_history_progress_id", "progress_history", ["progress_id"])
    op.create_index("ix_progress_history_session_id", "progress_history", ["session_id"])
    op.create_index("ix_progress_history_user_answer_id", "progress_history", ["user_answer_id"])

    op.create_table(
        "mistake_history",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("mistake_id", sa.BigInteger(), sa.ForeignKey("mistakes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_answer_id", sa.BigInteger(), sa.ForeignKey("user_answers.id", ondelete="SET NULL"), nullable=True),
        sa.Column("session_id", sa.BigInteger(), sa.ForeignKey("quiz_sessions.id", ondelete="SET NULL"), nullable=True),
        sa.Column("item_id", sa.String(length=255), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("previous_status", sa.String(length=32), nullable=True),
        sa.Column("new_status", sa.String(length=32), nullable=False),
        sa.Column("wrong_answer", sa.Text(), nullable=True),
        sa.Column("correct_answer", sa.Text(), nullable=True),
        sa.Column("metadata_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_mistake_history_user_created", "mistake_history", ["user_id", "created_at"])
    op.create_index("ix_mistake_history_mistake_id", "mistake_history", ["mistake_id"])
    op.create_index("ix_mistake_history_item_id", "mistake_history", ["item_id"])
    op.create_index("ix_mistake_history_session_id", "mistake_history", ["session_id"])

    op.create_table(
        "recommendations",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("level", sa.String(length=8), nullable=False),
        sa.Column("theme", sa.String(length=255), nullable=True),
        sa.Column("theme_key", sa.String(length=255), nullable=True),
        sa.Column("recommendation_type", sa.String(length=64), nullable=False),
        sa.Column("reason_code", sa.String(length=64), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("copy_de", sa.Text(), nullable=False),
        sa.Column("source_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("shown_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("acted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("priority >= 0", name="ck_recommendations_priority_non_negative"),
    )
    op.create_index("ix_recommendations_user_priority", "recommendations", ["user_id", "priority"])
    op.create_index("ix_recommendations_user_created", "recommendations", ["user_id", "created_at"])

    op.create_table(
        "api_error_logs",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("session_id", sa.BigInteger(), sa.ForeignKey("quiz_sessions.id", ondelete="SET NULL"), nullable=True),
        sa.Column("request_id", sa.String(length=255), nullable=True),
        sa.Column("endpoint", sa.String(length=255), nullable=False),
        sa.Column("status_code", sa.Integer(), nullable=True),
        sa.Column("error_category", sa.String(length=64), nullable=False),
        sa.Column("level", sa.String(length=8), nullable=True),
        sa.Column("theme", sa.String(length=255), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_api_error_logs_occurred_at", "api_error_logs", ["occurred_at"])
    op.create_index("ix_api_error_logs_error_category", "api_error_logs", ["error_category"])
    op.create_index("ix_api_error_logs_user_id", "api_error_logs", ["user_id"])
    op.create_index("ix_api_error_logs_session_id", "api_error_logs", ["session_id"])
    op.create_index("ix_api_error_logs_request_id", "api_error_logs", ["request_id"])


def downgrade() -> None:
    op.drop_table("api_error_logs")
    op.drop_table("recommendations")
    op.drop_table("mistake_history")
    op.drop_table("progress_history")

    op.drop_column("payments", "cancelled_at")
    op.drop_column("payments", "credited_at")

    op.drop_constraint("ck_mistakes_successful_repeat_days_non_negative", "mistakes", type_="check")
    op.drop_constraint("ck_mistakes_successful_repeats_non_negative", "mistakes", type_="check")
    op.drop_index("ix_mistakes_item_id", table_name="mistakes")
    op.drop_index("ix_mistakes_question_reference_id", table_name="mistakes")
    op.drop_constraint("fk_mistakes_question_reference_id", "mistakes", type_="foreignkey")
    op.drop_column("mistakes", "content_available")
    op.drop_column("mistakes", "last_successful_repeat_at")
    op.drop_column("mistakes", "last_repeated_at")
    op.drop_column("mistakes", "last_mistake_at")
    op.drop_column("mistakes", "first_mistake_at")
    op.drop_column("mistakes", "successful_repeat_days_count")
    op.drop_column("mistakes", "successful_repeats_count")
    op.drop_column("mistakes", "theme_key")
    op.drop_column("mistakes", "item_id")
    op.drop_column("mistakes", "question_reference_id")

    op.drop_constraint("ck_progress_available_non_negative", "progress", type_="check")
    op.drop_constraint("ck_progress_unique_items_non_negative", "progress", type_="check")
    op.drop_constraint("ck_progress_recency_percent", "progress", type_="check")
    op.drop_constraint("ck_progress_weakness_percent", "progress", type_="check")
    op.drop_constraint("ck_progress_stability_percent", "progress", type_="check")
    op.drop_constraint("ck_progress_coverage_percent", "progress", type_="check")
    op.drop_constraint("ck_progress_counts_lte_answered", "progress", type_="check")
    op.drop_constraint("ck_progress_wrong_count_non_negative", "progress", type_="check")
    op.drop_column("progress", "last_recalculated_at")
    op.drop_column("progress", "last_wrong_at")
    op.drop_column("progress", "available_items_count")
    op.drop_column("progress", "unique_items_seen")
    op.drop_column("progress", "topic_status")
    op.drop_column("progress", "recency_score")
    op.drop_column("progress", "weakness_score")
    op.drop_column("progress", "stability_score")
    op.drop_column("progress", "coverage_status")
    op.drop_column("progress", "coverage_score")
    op.drop_column("progress", "wrong_count")
    op.drop_column("progress", "theme_key")

    op.drop_constraint("uq_user_answers_telegram_update_id", "user_answers", type_="unique")
    op.drop_index("ix_user_answers_level_theme", table_name="user_answers")
    op.drop_index("ix_user_answers_question_reference_id", table_name="user_answers")
    op.drop_index("ix_user_answers_training_session_item_id", table_name="user_answers")
    op.drop_constraint("fk_user_answers_question_reference_id", "user_answers", type_="foreignkey")
    op.drop_constraint("fk_user_answers_training_session_item_id", "user_answers", type_="foreignkey")
    op.drop_column("user_answers", "telegram_update_id")
    op.drop_column("user_answers", "metadata_snapshot")
    op.drop_column("user_answers", "session_type")
    op.drop_column("user_answers", "theme_key")
    op.drop_column("user_answers", "theme")
    op.drop_column("user_answers", "level")
    op.drop_column("user_answers", "question_reference_id")
    op.drop_column("user_answers", "training_session_item_id")

    op.drop_table("training_session_items")
    op.drop_table("daily_limits")
    op.drop_table("question_references")

    op.drop_constraint("ck_quiz_sessions_answered_count_lte_total", "quiz_sessions", type_="check")
    op.drop_constraint("ck_quiz_sessions_answered_count_non_negative", "quiz_sessions", type_="check")
    op.drop_constraint("ck_quiz_sessions_shown_count_non_negative", "quiz_sessions", type_="check")
    op.drop_index("ix_quiz_sessions_user_status", table_name="quiz_sessions")
    op.drop_column("quiz_sessions", "answered_count")
    op.drop_column("quiz_sessions", "shown_questions_count")
    op.drop_column("quiz_sessions", "failed_at")
    op.drop_column("quiz_sessions", "abandoned_at")
    op.drop_column("quiz_sessions", "completed_at")
    op.drop_column("quiz_sessions", "session_type")
