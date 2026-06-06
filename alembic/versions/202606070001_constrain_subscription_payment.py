"""Constrain subscription payment linkage."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "202606070001"
down_revision = "202606050001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()

    null_payment_rows = connection.scalar(
        sa.text("SELECT count(*) FROM subscriptions WHERE payment_id IS NULL"),
    )
    if null_payment_rows:
        raise RuntimeError("Cannot enforce subscriptions.payment_id NOT NULL while NULL rows exist.")

    duplicate_payment_id = connection.scalar(
        sa.text(
            """
            SELECT payment_id
            FROM subscriptions
            WHERE payment_id IS NOT NULL
            GROUP BY payment_id
            HAVING count(*) > 1
            LIMIT 1
            """,
        ),
    )
    if duplicate_payment_id is not None:
        raise RuntimeError("Cannot enforce unique subscriptions.payment_id while duplicate rows exist.")

    orphan_payment_id = connection.scalar(
        sa.text(
            """
            SELECT s.payment_id
            FROM subscriptions s
            LEFT JOIN payments p ON p.id = s.payment_id
            WHERE p.id IS NULL
            LIMIT 1
            """,
        ),
    )
    if orphan_payment_id is not None:
        raise RuntimeError("Cannot add subscriptions.payment_id foreign key while orphan rows exist.")

    op.alter_column(
        "subscriptions",
        "payment_id",
        existing_type=sa.BigInteger(),
        nullable=False,
    )
    op.create_foreign_key(
        "fk_subscriptions_payment_id_payments",
        "subscriptions",
        "payments",
        ["payment_id"],
        ["id"],
    )
    op.create_unique_constraint(
        "uq_subscriptions_payment_id",
        "subscriptions",
        ["payment_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_subscriptions_payment_id",
        "subscriptions",
        type_="unique",
    )
    op.drop_constraint(
        "fk_subscriptions_payment_id_payments",
        "subscriptions",
        type_="foreignkey",
    )
    op.alter_column(
        "subscriptions",
        "payment_id",
        existing_type=sa.BigInteger(),
        nullable=True,
    )
