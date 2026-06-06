"""Require Telegram charge id for confirmed payments."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "202606070002"
down_revision = "202606070001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    invalid_confirmed_payments = op.get_bind().scalar(
        sa.text(
            """
            SELECT count(*)
            FROM payments
            WHERE status IN ('paid', 'credited')
              AND (
                telegram_payment_charge_id IS NULL
                OR trim(telegram_payment_charge_id) = ''
              )
            """,
        ),
    )
    if invalid_confirmed_payments:
        raise RuntimeError("Cannot enforce confirmed payment charge id while invalid payment rows exist.")

    op.create_check_constraint(
        "ck_payments_confirmed_telegram_charge_id",
        "payments",
        "status NOT IN ('paid', 'credited') "
        "OR (telegram_payment_charge_id IS NOT NULL AND trim(telegram_payment_charge_id) <> '')",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_payments_confirmed_telegram_charge_id",
        "payments",
        type_="check",
    )
