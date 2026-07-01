"""Add local quiz catalog schema."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "202606300001"
down_revision = "202606070002"
branch_labels = None
depends_on = None


def jsonb() -> postgresql.JSONB:
    return postgresql.JSONB(astext_type=sa.Text())


def upgrade() -> None:
    op.create_table(
        "quiz_catalogs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("catalog_id", sa.String(length=128), nullable=False),
        sa.Column("catalog_version", sa.String(length=128), nullable=False),
        sa.Column("source", sa.String(length=128), nullable=False),
        sa.Column("checksum", sa.String(length=128), nullable=False),
        sa.Column("manifest_checksum", sa.String(length=128), nullable=True),
        sa.Column("source_path", sa.Text(), nullable=True),
        sa.Column("item_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("imported_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("metadata", jsonb(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("catalog_id", "catalog_version", name="uq_quiz_catalogs_catalog_version"),
    )
    op.create_index("ix_quiz_catalogs_is_active", "quiz_catalogs", ["is_active"])

    op.create_table(
        "quiz_catalog_items",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("catalog_id", sa.String(length=128), nullable=False),
        sa.Column("catalog_version", sa.String(length=128), nullable=False),
        sa.Column("item_id", sa.String(length=255), nullable=False),
        sa.Column("item_version", sa.String(length=128), nullable=False),
        sa.Column("language", sa.String(length=16), server_default=sa.text("'de'"), nullable=False),
        sa.Column("level", sa.String(length=8), nullable=False),
        sa.Column("sublevel", sa.String(length=8), nullable=True),
        sa.Column("theme_id", sa.String(length=32), nullable=False),
        sa.Column("theme", sa.String(length=255), nullable=True),
        sa.Column("theme_slug", sa.String(length=255), nullable=True),
        sa.Column("subtheme_id", sa.String(length=128), nullable=True),
        sa.Column("objective_id", sa.String(length=128), nullable=True),
        sa.Column("pattern_id", sa.String(length=128), nullable=True),
        sa.Column("difficulty_band", sa.String(length=64), nullable=True),
        sa.Column("register", sa.String(length=128), nullable=True),
        sa.Column("prompt", sa.Text(), nullable=True),
        sa.Column("stem_text", sa.Text(), nullable=False),
        sa.Column("options", jsonb(), nullable=False),
        sa.Column("answer_key", sa.String(length=64), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=True),
        sa.Column("tags", jsonb(), nullable=True),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("source", sa.String(length=128), nullable=False),
        sa.Column("source_path", sa.Text(), nullable=True),
        sa.Column("checksum", sa.String(length=128), nullable=False),
        sa.Column("selection_key", sa.BigInteger(), nullable=False),
        sa.Column("imported_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("metadata", jsonb(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["catalog_id", "catalog_version"],
            ["quiz_catalogs.catalog_id", "quiz_catalogs.catalog_version"],
            name="fk_quiz_catalog_items_catalog_id",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "catalog_id",
            "catalog_version",
            "item_id",
            "item_version",
            name="uq_quiz_catalog_items_catalog_item_version",
        ),
    )
    op.create_index(
        "ix_qci_catalog_language_level_theme_status_active",
        "quiz_catalog_items",
        ["catalog_id", "catalog_version", "language", "level", "theme_id", "status", "is_active", "selection_key"],
    )
    op.create_index(
        "ix_qci_catalog_language_sublevel_theme_status_active",
        "quiz_catalog_items",
        ["catalog_id", "catalog_version", "language", "sublevel", "theme_id", "status", "is_active", "selection_key"],
    )
    op.create_index(
        "ix_quiz_catalog_items_catalog_status_active",
        "quiz_catalog_items",
        ["catalog_id", "catalog_version", "status", "is_active"],
    )
    op.create_index("ix_quiz_catalog_items_catalog_item", "quiz_catalog_items", ["catalog_id", "catalog_version", "item_id"])

    op.create_table(
        "quiz_catalog_import_runs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("catalog_id", sa.String(length=128), nullable=True),
        sa.Column("catalog_version", sa.String(length=128), nullable=True),
        sa.Column("source_path", sa.Text(), nullable=False),
        sa.Column("manifest_checksum", sa.String(length=128), nullable=True),
        sa.Column("dry_run", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("added_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("updated_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("skipped_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("failed_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("error_summary", jsonb(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["catalog_id", "catalog_version"],
            ["quiz_catalogs.catalog_id", "quiz_catalogs.catalog_version"],
            name="fk_quiz_catalog_import_runs_catalog_id",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_quiz_catalog_import_runs_catalog_started",
        "quiz_catalog_import_runs",
        ["catalog_id", "started_at"],
    )
    op.create_index("ix_quiz_catalog_import_runs_status", "quiz_catalog_import_runs", ["status"])

    op.add_column("quiz_sessions", sa.Column("catalog_id", sa.String(length=128), nullable=True))
    op.add_column("quiz_sessions", sa.Column("catalog_version", sa.String(length=128), nullable=True))
    op.create_index("ix_quiz_sessions_catalog_id", "quiz_sessions", ["catalog_id"])

    op.add_column("question_references", sa.Column("catalog_id", sa.String(length=128), nullable=True))
    op.add_column("question_references", sa.Column("item_version", sa.String(length=128), nullable=True))
    op.drop_constraint("uq_question_references_item_id", "question_references", type_="unique")
    op.create_unique_constraint(
        "uq_question_references_catalog_item_version",
        "question_references",
        ["catalog_id", "item_id", "item_version"],
    )
    op.create_index(
        "uq_question_references_api_item_id",
        "question_references",
        ["item_id"],
        unique=True,
        postgresql_where=sa.text("catalog_id IS NULL AND item_version IS NULL"),
        sqlite_where=sa.text("catalog_id IS NULL AND item_version IS NULL"),
    )
    op.create_index("ix_question_references_item_id", "question_references", ["item_id"])
    op.create_index("ix_question_references_catalog_item", "question_references", ["catalog_id", "item_id"])

    op.add_column("training_session_items", sa.Column("catalog_id", sa.String(length=128), nullable=True))
    op.add_column("training_session_items", sa.Column("item_version", sa.String(length=128), nullable=True))
    op.drop_constraint("uq_training_session_items_session_item", "training_session_items", type_="unique")
    op.create_index(
        "uq_training_session_items_session_item",
        "training_session_items",
        ["session_id", "item_id"],
        unique=True,
        postgresql_where=sa.text("catalog_id IS NULL AND item_version IS NULL"),
        sqlite_where=sa.text("catalog_id IS NULL AND item_version IS NULL"),
    )
    op.create_unique_constraint(
        "uq_training_session_items_session_catalog_item",
        "training_session_items",
        ["session_id", "catalog_id", "item_id", "item_version"],
    )
    op.create_check_constraint(
        "ck_training_session_items_catalog_scope_complete",
        "training_session_items",
        "(catalog_id IS NULL AND item_version IS NULL) "
        "OR (catalog_id IS NOT NULL AND item_version IS NOT NULL)",
    )
    op.create_index("ix_training_session_items_catalog_item", "training_session_items", ["catalog_id", "item_id"])

    op.add_column("user_answers", sa.Column("catalog_id", sa.String(length=128), nullable=True))
    op.add_column("user_answers", sa.Column("item_id", sa.String(length=255), nullable=True))
    op.add_column("user_answers", sa.Column("item_version", sa.String(length=128), nullable=True))
    op.execute("UPDATE user_answers SET item_id = external_quiz_id WHERE item_id IS NULL")
    op.create_unique_constraint(
        "uq_user_answers_user_session_catalog_item",
        "user_answers",
        ["user_id", "session_id", "catalog_id", "item_id", "item_version"],
    )
    op.create_index("ix_user_answers_catalog_item", "user_answers", ["catalog_id", "item_id", "item_version"])
    op.create_index(
        "ix_user_answers_user_topic_item",
        "user_answers",
        ["user_id", "level", "theme", "external_quiz_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_user_answers_user_topic_item", table_name="user_answers")
    op.drop_index("ix_user_answers_catalog_item", table_name="user_answers")
    op.drop_constraint("uq_user_answers_user_session_catalog_item", "user_answers", type_="unique")
    op.drop_column("user_answers", "item_version")
    op.drop_column("user_answers", "item_id")
    op.drop_column("user_answers", "catalog_id")

    op.execute("DELETE FROM training_session_items WHERE catalog_id IS NOT NULL OR item_version IS NOT NULL")
    op.drop_index("ix_training_session_items_catalog_item", table_name="training_session_items")
    op.drop_constraint(
        "ck_training_session_items_catalog_scope_complete",
        "training_session_items",
        type_="check",
    )
    op.drop_constraint("uq_training_session_items_session_catalog_item", "training_session_items", type_="unique")
    op.drop_index("uq_training_session_items_session_item", table_name="training_session_items")
    op.create_unique_constraint(
        "uq_training_session_items_session_item",
        "training_session_items",
        ["session_id", "item_id"],
    )
    op.drop_column("training_session_items", "item_version")
    op.drop_column("training_session_items", "catalog_id")

    op.drop_index("ix_question_references_item_id", table_name="question_references")
    op.drop_index("ix_question_references_catalog_item", table_name="question_references")
    op.drop_index("uq_question_references_api_item_id", table_name="question_references")
    op.drop_constraint("uq_question_references_catalog_item_version", "question_references", type_="unique")
    op.execute(
        """
        DELETE FROM training_session_items
        WHERE question_reference_id IN (
            SELECT id
            FROM question_references
            WHERE catalog_id IS NOT NULL OR item_version IS NOT NULL
        )
        """,
    )
    op.execute("DELETE FROM question_references WHERE catalog_id IS NOT NULL OR item_version IS NOT NULL")
    op.create_unique_constraint("uq_question_references_item_id", "question_references", ["item_id"])
    op.drop_column("question_references", "item_version")
    op.drop_column("question_references", "catalog_id")

    op.drop_index("ix_quiz_sessions_catalog_id", table_name="quiz_sessions")
    op.drop_column("quiz_sessions", "catalog_version")
    op.drop_column("quiz_sessions", "catalog_id")

    op.drop_index("ix_quiz_catalog_import_runs_status", table_name="quiz_catalog_import_runs")
    op.drop_index("ix_quiz_catalog_import_runs_catalog_started", table_name="quiz_catalog_import_runs")
    op.drop_table("quiz_catalog_import_runs")

    op.drop_index("ix_quiz_catalog_items_catalog_item", table_name="quiz_catalog_items")
    op.drop_index("ix_quiz_catalog_items_catalog_status_active", table_name="quiz_catalog_items")
    op.drop_index("ix_qci_catalog_language_sublevel_theme_status_active", table_name="quiz_catalog_items")
    op.drop_index("ix_qci_catalog_language_level_theme_status_active", table_name="quiz_catalog_items")
    op.drop_table("quiz_catalog_items")

    op.drop_index("ix_quiz_catalogs_is_active", table_name="quiz_catalogs")
    op.drop_table("quiz_catalogs")
