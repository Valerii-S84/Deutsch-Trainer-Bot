"""Add Telegram payment charge id uniqueness."""

from __future__ import annotations

from alembic import op


revision = "202606050001"
down_revision = "202605140002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_payments_telegram_payment_charge_id",
        "payments",
        ["telegram_payment_charge_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_payments_telegram_payment_charge_id",
        "payments",
        type_="unique",
    )
