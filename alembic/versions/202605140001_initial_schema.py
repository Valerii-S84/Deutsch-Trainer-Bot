"""Create initial production data layer tables for milestone 2."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "202605140001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("telegram_user_id", sa.BigInteger(), nullable=False),
        sa.Column("username", sa.String(length=255), nullable=True),
        sa.Column("first_name", sa.String(length=255), nullable=True),
        sa.Column("language_code", sa.String(length=16), nullable=True),
        sa.Column("selected_level", sa.String(length=8), nullable=True),
        sa.Column("selected_theme", sa.String(length=255), nullable=True),
        sa.Column("is_blocked", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("status", sa.String(length=32), nullable=False, server_default=sa.text("'active'")),
        sa.Column("last_active_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("telegram_user_id", name="uq_users_telegram_user_id"),
        sa.Index("ix_users_telegram_user_id", "telegram_user_id", unique=True),
        sa.Index("ix_users_language_code", "language_code"),
    )

    op.create_table(
        "quiz_sessions",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("level", sa.String(length=8), nullable=False),
        sa.Column("theme", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False, server_default=sa.text("'created'")),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("total_questions", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("correct_answers", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("source", sa.String(length=64), nullable=False, server_default=sa.text("'quiz_bank_api'")),
        sa.Column("source_metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("api_request_id", sa.String(length=255), nullable=True),
        sa.Column("api_metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("correct_answers >= 0", name="ck_quiz_sessions_correct_answers_non_negative"),
        sa.CheckConstraint("total_questions >= 0", name="ck_quiz_sessions_total_questions_non_negative"),
        sa.CheckConstraint("correct_answers <= total_questions", name="ck_quiz_sessions_correct_answers_lte_total"),
        sa.Index("ix_quiz_sessions_user_id", "user_id"),
    )

    op.create_table(
        "user_answers",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("session_id", sa.BigInteger(), sa.ForeignKey("quiz_sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("external_quiz_id", sa.String(length=255), nullable=False),
        sa.Column("selected_answer", sa.Text(), nullable=False),
        sa.Column("correct_answer", sa.Text(), nullable=False),
        sa.Column("is_correct", sa.Boolean(), nullable=False),
        sa.Column("answered_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("response_time_ms", sa.Integer(), nullable=True),
        sa.Column("quiz_source", sa.String(length=64), nullable=True),
        sa.Column("external_ref", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint(
            "user_id",
            "session_id",
            "external_quiz_id",
            name="uq_user_answers_user_session_external_quiz",
        ),
        sa.Index("ix_user_answers_user_id", "user_id"),
        sa.Index("ix_user_answers_session_id", "session_id"),
        sa.Index("ix_user_answers_external_quiz_id", "external_quiz_id"),
    )

    op.create_table(
        "progress",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("level", sa.String(length=8), nullable=False),
        sa.Column("theme", sa.String(length=255), nullable=False),
        sa.Column("total_answered", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_correct", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("accuracy", sa.Numeric(5, 2), nullable=False, server_default="0"),
        sa.Column("streak", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_answered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("user_id", "level", "theme", name="uq_progress_user_level_theme"),
        sa.CheckConstraint("total_answered >= 0", name="ck_progress_total_answered_non_negative"),
        sa.CheckConstraint("total_correct >= 0", name="ck_progress_total_correct_non_negative"),
        sa.CheckConstraint("total_correct <= total_answered", name="ck_progress_correct_lte_answered"),
        sa.CheckConstraint("accuracy >= 0 AND accuracy <= 100", name="ck_progress_accuracy_percent"),
        sa.CheckConstraint("streak >= 0", name="ck_progress_streak_non_negative"),
        sa.Index("ix_progress_user_id", "user_id"),
        sa.Index("ix_progress_level_theme", "level", "theme"),
    )

    op.create_table(
        "mistakes",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("external_quiz_id", sa.String(length=255), nullable=False),
        sa.Column("level", sa.String(length=8), nullable=False),
        sa.Column("theme", sa.String(length=255), nullable=False),
        sa.Column("wrong_answer", sa.Text(), nullable=False),
        sa.Column("correct_answer", sa.Text(), nullable=False),
        sa.Column("mistake_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default=sa.text("'new'")),
        sa.Column("source_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Index("ix_mistakes_user_id", "user_id"),
        sa.Index("ix_mistakes_external_quiz_id", "external_quiz_id"),
        sa.Index(
            "ix_mistakes_active_user_external",
            "user_id",
            "external_quiz_id",
            unique=True,
            postgresql_where=sa.text("resolved_at IS NULL"),
        ),
        sa.CheckConstraint("mistake_count > 0", name="ck_mistakes_mistake_count_positive"),
    )

    op.create_table(
        "subscriptions",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("plan", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default=sa.text("'active'")),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source", sa.String(length=64), nullable=False, server_default=sa.text("'telegram_stars'")),
        sa.Column("provider_reference", sa.String(length=255), nullable=True),
        sa.Column("payment_id", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Index("ix_subscriptions_user_id", "user_id"),
        sa.Index("ix_subscriptions_status_expires_at", "status", "expires_at"),
        sa.CheckConstraint("expires_at IS NULL OR started_at IS NULL OR expires_at >= started_at", name="ck_subscriptions_dates"),
    )

    op.create_table(
        "payments",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("telegram_payment_charge_id", sa.String(length=255), nullable=True),
        sa.Column("provider_payment_charge_id", sa.String(length=255), nullable=True),
        sa.Column("plan", sa.String(length=16), nullable=False),
        sa.Column("amount_stars", sa.Integer(), nullable=False),
        sa.Column("config_reference", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False, server_default=sa.text("'created'")),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source", sa.String(length=64), nullable=False, server_default=sa.text("'telegram_stars'")),
        sa.Column("audit_metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Index("ix_payments_user_id", "user_id"),
        sa.UniqueConstraint("idempotency_key", name="uq_payments_idempotency_key"),
        sa.UniqueConstraint("provider_payment_charge_id", name="uq_payments_provider_payment_charge_id"),
        sa.CheckConstraint("amount_stars >= 0", name="ck_payments_amount_stars_non_negative"),
    )

    op.create_table(
        "analytics_events",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("event_name", sa.String(length=128), nullable=False),
        sa.Column("event_time", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("event_metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("session_id", sa.BigInteger(), sa.ForeignKey("quiz_sessions.id", ondelete="SET NULL"), nullable=True),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Index("ix_analytics_events_user_id", "user_id"),
        sa.Index("ix_analytics_events_session_id", "session_id"),
        sa.Index("ix_analytics_events_event_name_time", "event_name", "event_time"),
    )


def downgrade() -> None:
    op.drop_table("analytics_events")
    op.drop_table("payments")
    op.drop_table("subscriptions")
    op.drop_table("mistakes")
    op.drop_table("progress")
    op.drop_table("user_answers")
    op.drop_table("quiz_sessions")
    op.drop_table("users")
