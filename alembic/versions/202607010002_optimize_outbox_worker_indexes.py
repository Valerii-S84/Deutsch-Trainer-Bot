"""Optimize outbox worker claim and stale-requeue indexes."""

from __future__ import annotations

from alembic import op


revision = "202607010002"
down_revision = "202607010001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_outbox_events_status_next_attempt_created",
        "outbox_events",
        ["status", "next_attempt_at", "created_at", "id"],
    )
    op.create_index(
        "ix_outbox_events_status_locked_at",
        "outbox_events",
        ["status", "locked_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_outbox_events_status_locked_at", table_name="outbox_events")
    op.drop_index("ix_outbox_events_status_next_attempt_created", table_name="outbox_events")
