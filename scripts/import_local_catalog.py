#!/usr/bin/env python3
"""Import a snapshot quiz bank into local catalog PostgreSQL tables."""

from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import asdict
from pathlib import Path
from typing import Sequence

from app.catalog import CatalogImportOptions, LocalCatalogImporter
from app.config import get_settings
from app.db.session import get_session


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    settings = get_settings()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-path", default=settings.catalog_source_path)
    parser.add_argument("--catalog-id", default=settings.active_catalog_id)
    parser.add_argument("--catalog-version", required=True)
    parser.add_argument("--source", default="production_quiz_bank_snapshot")
    parser.add_argument("--dry-run", action="store_true", default=settings.catalog_import_dry_run)
    args = parser.parse_args(argv)
    if not args.catalog_id:
        parser.error("--catalog-id or ACTIVE_CATALOG_ID is required")
    return args


async def run_import(args: argparse.Namespace) -> int:
    options = CatalogImportOptions(
        catalog_id=args.catalog_id,
        catalog_version=args.catalog_version,
        source_path=Path(args.source_path),
        source=args.source,
        dry_run=args.dry_run,
    )
    async with get_session() as session:
        async with session.begin():
            report = await LocalCatalogImporter().import_catalog(session, options)
    print(json.dumps(asdict(report), ensure_ascii=False, sort_keys=True, indent=2))
    return 1 if report.errors else 0


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    return asyncio.run(run_import(args))


if __name__ == "__main__":
    raise SystemExit(main())
