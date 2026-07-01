from __future__ import annotations

from datetime import datetime
from typing import Optional

import sqlalchemy as sa
from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKeyConstraint, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.db.base import Base, TimestampMixin
from app.db.types import json_document_type

BIGINT_PK = BigInteger().with_variant(Integer, "sqlite")


class QuizCatalog(Base, TimestampMixin):
    """Imported read-only quiz catalog version available for local gameplay."""

    __tablename__ = "quiz_catalogs"

    id: Mapped[int] = mapped_column(BIGINT_PK, primary_key=True, autoincrement=True)
    catalog_id: Mapped[str] = mapped_column(String(128), nullable=False)
    catalog_version: Mapped[str] = mapped_column(String(128), nullable=False)
    source: Mapped[str] = mapped_column(String(128), nullable=False)
    checksum: Mapped[str] = mapped_column(String(128), nullable=False)
    manifest_checksum: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    source_path: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    item_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=sa.text("0"))
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=sa.text("true"))
    catalog_metadata: Mapped[Optional[dict[str, object]]] = mapped_column(
        "metadata",
        json_document_type(),
        nullable=True,
    )

    items = relationship("QuizCatalogItem", back_populates="catalog")

    __table_args__ = (
        UniqueConstraint("catalog_id", "catalog_version", name="uq_quiz_catalogs_catalog_version"),
        Index("ix_quiz_catalogs_is_active", "is_active"),
    )


class QuizCatalogItem(Base, TimestampMixin):
    """Single immutable quiz item imported from a catalog snapshot."""

    __tablename__ = "quiz_catalog_items"

    id: Mapped[int] = mapped_column(BIGINT_PK, primary_key=True, autoincrement=True)
    catalog_id: Mapped[str] = mapped_column(String(128), nullable=False)
    catalog_version: Mapped[str] = mapped_column(String(128), nullable=False)
    item_id: Mapped[str] = mapped_column(String(255), nullable=False)
    item_version: Mapped[str] = mapped_column(String(128), nullable=False)
    language: Mapped[str] = mapped_column(String(16), nullable=False, default="de", server_default=sa.text("'de'"))
    level: Mapped[str] = mapped_column(String(8), nullable=False)
    sublevel: Mapped[Optional[str]] = mapped_column(String(8), nullable=True)
    theme_id: Mapped[str] = mapped_column(String(32), nullable=False)
    theme: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    theme_slug: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    subtheme_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    objective_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    pattern_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    difficulty_band: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    register: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    prompt: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    stem_text: Mapped[str] = mapped_column(Text, nullable=False)
    options: Mapped[list[object]] = mapped_column(json_document_type(), nullable=False)
    answer_key: Mapped[str] = mapped_column(String(64), nullable=False)
    explanation: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    tags: Mapped[Optional[list[object]]] = mapped_column(json_document_type(), nullable=True)
    status: Mapped[str] = mapped_column(String(64), nullable=False)
    source: Mapped[str] = mapped_column(String(128), nullable=False)
    source_path: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    checksum: Mapped[str] = mapped_column(String(128), nullable=False)
    selection_key: Mapped[int] = mapped_column(BigInteger, nullable=False)
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=sa.text("true"))
    item_metadata: Mapped[Optional[dict[str, object]]] = mapped_column(
        "metadata",
        json_document_type(),
        nullable=True,
    )

    catalog = relationship("QuizCatalog", back_populates="items")

    __table_args__ = (
        ForeignKeyConstraint(
            ["catalog_id", "catalog_version"],
            ["quiz_catalogs.catalog_id", "quiz_catalogs.catalog_version"],
            name="fk_quiz_catalog_items_catalog_id",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "catalog_id",
            "catalog_version",
            "item_id",
            "item_version",
            name="uq_quiz_catalog_items_catalog_item_version",
        ),
        Index(
            "ix_qci_catalog_language_level_theme_status_active",
            "catalog_id",
            "catalog_version",
            "language",
            "level",
            "theme_id",
            "status",
            "is_active",
            "selection_key",
        ),
        Index(
            "ix_qci_catalog_language_sublevel_theme_status_active",
            "catalog_id",
            "catalog_version",
            "language",
            "sublevel",
            "theme_id",
            "status",
            "is_active",
            "selection_key",
        ),
        Index("ix_quiz_catalog_items_catalog_status_active", "catalog_id", "catalog_version", "status", "is_active"),
        Index("ix_quiz_catalog_items_catalog_item", "catalog_id", "catalog_version", "item_id"),
    )


class QuizCatalogImportRun(Base, TimestampMixin):
    """Audit row for a local catalog import or dry-run validation."""

    __tablename__ = "quiz_catalog_import_runs"

    id: Mapped[int] = mapped_column(BIGINT_PK, primary_key=True, autoincrement=True)
    catalog_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    catalog_version: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    source_path: Mapped[str] = mapped_column(Text, nullable=False)
    manifest_checksum: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    dry_run: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=sa.text("false"))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    added_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=sa.text("0"))
    updated_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=sa.text("0"))
    skipped_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=sa.text("0"))
    failed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=sa.text("0"))
    error_summary: Mapped[Optional[dict[str, object]]] = mapped_column(json_document_type(), nullable=True)

    __table_args__ = (
        ForeignKeyConstraint(
            ["catalog_id", "catalog_version"],
            ["quiz_catalogs.catalog_id", "quiz_catalogs.catalog_version"],
            name="fk_quiz_catalog_import_runs_catalog_id",
            ondelete="SET NULL",
        ),
        Index("ix_quiz_catalog_import_runs_catalog_started", "catalog_id", "started_at"),
        Index("ix_quiz_catalog_import_runs_status", "status"),
    )
