#!/usr/bin/env python3
"""Run read-only Quiz Bank live/staging smoke checks without printing secrets."""

from __future__ import annotations

import asyncio
import os
import re
import sys
from collections.abc import Iterable
from hashlib import sha256

from app.quiz_bank.client import QuizBankAsyncClient
from app.quiz_bank.errors import QuizBankError
from app.quiz_bank.schemas import QuizBankRequestContext, QuizItem
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
        return asyncio.run(run_smoke(levels))
    except QuizBankError as exc:
        print(f"[quiz_bank_live_smoke] failed: {redact_sensitive_output(str(exc))}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(
            f"[quiz_bank_live_smoke] failed: {redact_sensitive_output(exc.__class__.__name__)}",
            file=sys.stderr,
        )
        return 1


async def run_smoke(levels: tuple[str, ...]) -> int:
    client = QuizBankAsyncClient()
    service = QuizBankService(client=client)
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
            themes = await service.get_themes(level=level)
            if not themes.themes:
                raise QuizBankError(f"Quiz Bank themes missing available content for {level}")
            theme = themes.themes[0]
            theme_value = theme.theme_key or theme.theme

            availability = await service.get_availability(level=level, theme=theme_value)
            if availability.available_items_count <= 0:
                raise QuizBankError(f"Quiz Bank availability has no items for {level}")

            questions = await service.request_quiz(
                level=level,
                theme=theme_value,
                limit=1,
                user_context=QuizBankRequestContext(session_type="live_smoke", target_level=level),
            )
            if questions.returned_count < 1 or not questions.items:
                raise QuizBankError(f"Quiz Bank question fetch returned no items for {level}")
            assert_no_cyrillic_dynamic_content(questions.items[0])
            print(
                "[quiz_bank_live_smoke] question fetch passed "
                f"level={level} item_hash={safe_fingerprint(questions.items[0].item_id)}"
            )
    finally:
        await client.close()

    print("[quiz_bank_live_smoke] live Quiz Bank smoke passed")
    return 0


def parse_levels(raw_value: str | None) -> tuple[str, ...]:
    if not raw_value:
        return DEFAULT_LEVELS
    levels = tuple(part.strip().upper() for part in raw_value.split(",") if part.strip())
    if not levels:
        raise QuizBankError("QUIZ_BANK_SMOKE_LEVELS must include at least one level")
    return levels


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
