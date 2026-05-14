from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


def json_document_type() -> sa.JSON:
    """Use PostgreSQL JSONB in production and portable JSON in tests."""
    return sa.JSON().with_variant(JSONB(), "postgresql")
