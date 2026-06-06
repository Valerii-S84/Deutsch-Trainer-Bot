#!/usr/bin/env python3
"""Run read-only Quiz Bank live/staging smoke checks without printing secrets."""

from __future__ import annotations

import asyncio
import os
import re
import sys
from collections.abc import Mapping
from hashlib import sha256

from app.config import Settings, get_settings
from app.quiz_bank.client import QuizBankAsyncClient
from app.quiz_bank.errors import QuizBankError
from app.quiz_bank.schemas import QuizItem, QuizTheme
from app.quiz_bank.service import QuizBankService


DEFAULT_LEVELS = ("A1", "A2", "B1")
CYRILLIC_RE = re.compile(r"[\u0400-\u04FF]")
SECRET_PATTERNS = (
    re.compile(r"\b\d{8,12}:[A-Za-z0-9_-]{35,}\b"),
    re.compile(r"(?i)\b(bearer\s+)[A-Za-z0-9._~+/=-]{12,}"),
    re.compile(r"(?i)\b(authorization\s*[:=]\s*)[^\s]+"),
    re.compile(r"(?i)\b(api[_-]?key|token|secret|password|credential)\b\s*[:=]\s*['\"]?[^'\"\s]{8,}"),
    re.compile(r"postgresql(?:\+asyncpg)?://[^\s'\"\)]+"),
    re.compile(r"redis://[^\s'\"\)]+"),
)


def main() -> int:
    try:
        levels = parse_levels(os.environ.get("QUIZ_BANK_SMOKE_LEVELS"))
        smoke_item_ids_by_level = parse_smoke_item_ids(os.environ.get("QUIZ_BANK_SMOKE_ITEM_IDS"))
        return asyncio.run(run_smoke(levels, smoke_item_ids_by_level=smoke_item_ids_by_level))
    except QuizBankError as exc:
        print(f"[quiz_bank_live_smoke] failed: {redact_sensitive_output(str(exc))}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(
            f"[quiz_bank_live_smoke] failed: {redact_sensitive_output(exc.__class__.__name__)}",
            file=sys.stderr,
        )
        return 1


def build_smoke_client(settings: Settings) -> QuizBankAsyncClient:
    return QuizBankAsyncClient(
        base_url=settings.quiz_bank_api_base_url,
        edge_api_key=settings.quiz_bank_edge_api_key_or_legacy,
        consumer_api_key=settings.quiz_bank_consumer_api_key.get_secret_value()
        if settings.quiz_bank_consumer_api_key
        else None,
        consumer_id=settings.quiz_bank_consumer_id,
        timeout_seconds=settings.quiz_bank_timeout_seconds,
        max_retries=settings.quiz_bank_max_retries,
        settings=settings,
    )


async def run_smoke(
    levels: tuple[str, ...],
    *,
    smoke_item_ids_by_level: Mapping[str, str] | None = None,
    service: QuizBankService | None = None,
) -> int:
    client = None
    if service is None:
        settings = get_settings()
        client = build_smoke_client(settings)
        service = QuizBankService(client=client, settings=settings)

    try:
        health = await service.get_health()
        if health.status != "ok":
            raise QuizBankError("Quiz Bank health status is not ok")
        print("[quiz_bank_live_smoke] health passed")

        levels_response = await service.get_levels()
        active_levels = {level.code for level in levels_response.levels if level.is_active}
        missing_levels = sorted(set(levels) - active_levels)
        if missing_levels:
            raise QuizBankError(f"Quiz Bank levels missing active required levels: {', '.join(missing_levels)}")
        print(f"[quiz_bank_live_smoke] levels passed count={len(active_levels)}")

        for level in levels:
            smoke_item_id = (smoke_item_ids_by_level or {}).get(level)
            await check_level(service, level=level, smoke_item_id=smoke_item_id)
    finally:
        if client is not None:
            await client.close()

    print("[quiz_bank_live_smoke] live Quiz Bank read-only smoke passed")
    return 0


async def check_level(service: QuizBankService, *, level: str, smoke_item_id: str | None) -> None:
    theme = await first_available_theme(service, level=level)
    await assert_theme_title_resolves(service, level=level, theme=theme)
    await assert_available_content(service, level=level, theme_value=theme.theme)
    await check_optional_question_lookup(service, level=level, smoke_item_id=smoke_item_id)


async def first_available_theme(service: QuizBankService, *, level: str) -> QuizTheme:
    themes = await service.get_themes(level=level)
    if not themes.themes:
        raise QuizBankError(f"Quiz Bank themes missing available content for {level}")
    return themes.themes[0]


async def assert_theme_title_resolves(service: QuizBankService, *, level: str, theme: QuizTheme) -> None:
    resolved_theme_ids = await service.resolve_theme_ids(theme=theme.theme)
    if not resolved_theme_ids:
        raise QuizBankError(f"Quiz Bank theme title did not resolve to an API theme id for {level}")
    if theme.theme_key not in resolved_theme_ids:
        raise QuizBankError(f"Quiz Bank theme title resolved to a different API theme id for {level}")
    print(
        "[quiz_bank_live_smoke] theme title resolution passed "
        f"level={level} theme_hash={safe_fingerprint(theme.theme_key)}"
    )


async def assert_available_content(service: QuizBankService, *, level: str, theme_value: str) -> None:
    availability = await service.get_availability(level=level, theme=theme_value)
    if availability.available_items_count <= 0:
        raise QuizBankError(f"Quiz Bank availability has no items for {level}")


async def check_optional_question_lookup(
    service: QuizBankService,
    *,
    level: str,
    smoke_item_id: str | None,
) -> None:
    if not smoke_item_id:
        print(f"[quiz_bank_live_smoke] question lookup skipped level={level} reason=no_smoke_item_id")
        return

    question = await service.get_question(item_id=smoke_item_id)
    if question.level != level:
        raise QuizBankError(f"Quiz Bank smoke item level mismatch for {level}")
    assert_no_cyrillic_dynamic_content(question)
    print(
        "[quiz_bank_live_smoke] question lookup passed "
        f"level={level} item_hash={safe_fingerprint(question.item_id)}"
    )


def parse_levels(raw_value: str | None) -> tuple[str, ...]:
    if not raw_value:
        return DEFAULT_LEVELS
    levels = tuple(part.strip().upper() for part in raw_value.split(",") if part.strip())
    if not levels:
        raise QuizBankError("QUIZ_BANK_SMOKE_LEVELS must include at least one level")
    return levels


def parse_smoke_item_ids(raw_value: str | None) -> dict[str, str]:
    if not raw_value:
        return {}

    item_ids_by_level: dict[str, str] = {}
    for part in raw_value.split(","):
        item = part.strip()
        if not item:
            continue
        level, separator, item_id = item.partition("=")
        if not separator:
            raise QuizBankError("QUIZ_BANK_SMOKE_ITEM_IDS entries must use LEVEL=item_id")
        level = level.strip().upper()
        item_id = item_id.strip()
        if not level or not item_id:
            raise QuizBankError("QUIZ_BANK_SMOKE_ITEM_IDS entries must include level and item_id")
        item_ids_by_level[level] = item_id
    return item_ids_by_level


def assert_no_cyrillic_dynamic_content(item: QuizItem) -> None:
    findings = [text for text in quiz_item_texts(item) if CYRILLIC_RE.search(text)]
    if findings:
        raise QuizBankError("Quiz Bank dynamic content contains Cyrillic text")


def quiz_item_texts(item: QuizItem) -> tuple[str, ...]:
    explanation = item.explanation.text if hasattr(item.explanation, "text") else str(item.explanation)
    return (
        item.question_text,
        item.theme,
        explanation,
        *(option.text for option in item.answer_options),
    )


def safe_fingerprint(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()[:12]


def redact_sensitive_output(value: str) -> str:
    redacted = value
    for pattern in SECRET_PATTERNS:
        redacted = pattern.sub(lambda match: _redact_match(match), redacted)
    return redacted


def _redact_match(match: re.Match[str]) -> str:
    if match.lastindex:
        prefix = match.group(1) or ""
        return f"{prefix}[REDACTED]"
    return "[REDACTED]"


if __name__ == "__main__":
    raise SystemExit(main())
