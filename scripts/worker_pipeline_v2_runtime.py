from __future__ import annotations

import argparse
import asyncio
import contextlib
import contextvars
import json
import math
import os
import subprocess
import sys
import threading
import time
import traceback
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

try:
    import resource as _resource
except ModuleNotFoundError:
    _resource = None
import asyncpg
from redis.asyncio import Redis
from sqlalchemy import insert
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


USER_COUNT = 100_000
DEFAULT_SESSION_COUNT = 5_000
DEFAULT_TARGET_RPS = 100
DEFAULT_TOTAL_REQUESTS = 500
DEFAULT_ARRIVAL_MODE = "steady"
DEFAULT_BURST_WINDOW_SECONDS = 1.0
DEFAULT_BURST_INTERVAL_SECONDS = 5.0
ARRIVAL_MODE_BURST = "burst"
DEFAULT_SESSION_SELECTION = "unique"
SESSION_SELECTION_HOTSET = "hotset"
DEFAULT_HOT_SESSION_RATIO = 0.0
DEFAULT_HOT_SESSION_POOL_SIZE = 100
SESSION_SELECTION_BUCKETS = 1_000
DEFAULT_CPU_PROFILE_INTERVAL_MS = 10.0
ERROR_SAMPLE_LIMIT = 5
CPU_PROFILE_TOPN = 20
SEED_BATCH_SIZE = 5_000
APP_NAME = "dtb_regression_isolation"
CATALOG_ID = "dtb-evidence-20260701"
CATALOG_VERSION = "2026-07-01-evidence"
ITEM_ID = "q_regular"
ITEM_VERSION = "1.0"
QUESTION_REFERENCE_ID = 1
QUESTION_TEXT = "Was ist korrekt?"
THEME = "Alltag"
THEME_KEY = "T01"
THEME_ID = "T01"
LEVEL = "A1"
AVAILABLE_ITEMS_COUNT = 599
CORRECT_ANSWER = "a2"
SELECTED_ANSWER = "a1"
QUESTION_OPTIONS = (
    {"option_id": "a1", "text": "Antwort A"},
    {"option_id": "a2", "text": "Antwort B"},
)


from scripts.worker_pipeline_v2_regression_isolation import *


async def seed_database(_args: argparse.Namespace) -> None:
    from app.db.models import QuizSession, TrainingSessionItem

    if _args.session_count <= 0:
        raise SystemExit("--session-count must be greater than 0")
    if _args.session_count > USER_COUNT:
        raise SystemExit("--session-count exceeds available seeded users")

    engine = create_async_engine(database_url(), future=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async with session_factory() as db:
        await _seed_users(db)
        await _seed_question_reference(db)
        quiz_rows, session_item_rows, pending_payloads = _session_seed_rows(_args.session_count)
        await db.execute(insert(QuizSession), quiz_rows)
        await db.execute(insert(TrainingSessionItem), session_item_rows)
        await db.commit()

    await engine.dispose()
    redis_seeded = await _seed_pending_answer_cache(pending_payloads)
    _print_seed_summary(_args.session_count, redis_seeded)


async def _seed_users(db) -> None:
    from app.db.models import User

    for start in range(1, USER_COUNT + 1, SEED_BATCH_SIZE):
        end = min(USER_COUNT + 1, start + SEED_BATCH_SIZE)
        rows = [{"id": user_id, "telegram_user_id": 7_000_000_000 + user_id} for user_id in range(start, end)]
        await db.execute(insert(User), rows)


async def _seed_question_reference(db) -> None:
    from app.db.models import QuestionReference

    row = {
        "id": QUESTION_REFERENCE_ID,
        "catalog_id": CATALOG_ID,
        "item_id": ITEM_ID,
        "item_version": ITEM_VERSION,
        "level": LEVEL,
        "theme": THEME,
        "theme_key": THEME_KEY,
        "source": "local_quiz_catalog",
        "metadata_snapshot": {
            "catalog_id": CATALOG_ID,
            "theme_id": THEME_ID,
            "progress_theme_key": "alltag",
            "content_version": ITEM_VERSION,
        },
        "content_version": ITEM_VERSION,
        "question_text_snapshot": QUESTION_TEXT,
        "correct_answer_snapshot": "Antwort B",
        "explanation_snapshot": "Richtig erklaert.",
    }
    await db.execute(insert(QuestionReference), [row])


def _session_seed_rows(session_count: int):
    quiz_rows: list[dict[str, object]] = []
    session_item_rows: list[dict[str, object]] = []
    pending_payloads: list[dict[str, object]] = []
    for session_id in range(1, session_count + 1):
        pending = answer_payload(session_id=session_id, question_token=f"tok{session_id:08d}", training_session_item_id=session_id)
        pending_payloads.append(pending)
        quiz_rows.append(_quiz_session_row(session_id, pending))
        session_item_rows.append(_session_item_row(session_id))
    return quiz_rows, session_item_rows, pending_payloads


def _quiz_session_row(session_id: int, pending: dict[str, object]) -> dict[str, object]:
    return {
        "id": session_id, "user_id": session_id, "level": LEVEL, "theme": THEME,
        "session_type": "regular", "status": "active", "total_questions": 5,
        "shown_questions_count": 1, "answered_count": 0, "correct_answers": 0,
        "catalog_id": CATALOG_ID, "catalog_version": CATALOG_VERSION, "source": "local_quiz_catalog",
        "source_metadata": {"theme_key": THEME_KEY}, "api_metadata": {"pending_question": pending},
    }


def _session_item_row(session_id: int) -> dict[str, object]:
    return {
        "id": session_id, "session_id": session_id, "user_id": session_id,
        "question_reference_id": QUESTION_REFERENCE_ID, "catalog_id": CATALOG_ID,
        "item_id": ITEM_ID, "item_version": ITEM_VERSION, "position": 1,
        "status": "shown", "shown_at": datetime.now(UTC),
    }


def _print_seed_summary(session_count: int, redis_seeded: int) -> None:
    seeded = {
        "users": USER_COUNT, "active_sessions": session_count,
        "pending_question_payloads": session_count, "redis_pending_question_payloads": redis_seeded,
        "question_references": 1, "catalog_id": CATALOG_ID,
    }
    print(json.dumps({"seeded": seeded}, indent=2))


async def _seed_pending_answer_cache(payloads: list[dict[str, object]]) -> int:
    if not os.environ.get("REDIS_URL"):
        return 0
    client = Redis.from_url(redis_url(), decode_responses=True)
    try:
        pipe = client.pipeline()
        for payload in payloads:
            session_id = int(payload["session_id"])
            question_token = str(payload["question_token"])
            key = f"dtb:training:pending_question:{session_id}:{question_token}"
            pipe.set(key, json.dumps(payload, ensure_ascii=False, separators=(",", ":")), ex=600)
        await pipe.execute()
        return len(payloads)
    finally:
        await client.aclose()


async def run_scenario(args: argparse.Namespace) -> None:
    from scripts.worker_pipeline_v2_scenario import ScenarioRunner

    await ScenarioRunner(args).run()


def sum_counters(counters) -> Counter[str]:
    total: Counter[str] = Counter()
    for counter in counters:
        total.update(counter)
    return total


def summarize_spans(requests: list[RequestMetrics]) -> dict[str, float]:
    values: dict[str, list[float]] = defaultdict(list)
    for metrics in requests:
        for name, value in metrics.timing_spans_ms.items():
            values[name].append(value)
    return {name: percentile(items, 0.95) for name, items in sorted(values.items())}


def redact_url(value: str) -> str:
    parsed = make_url(value)
    safe = parsed.set(password="***")
    return safe.render_as_string(hide_password=False)


def redact_redis_url(value: str) -> str:
    if "@" not in value:
        return value
    prefix, suffix = value.rsplit("@", 1)
    if ":" not in prefix:
        return value
    return "***@" + suffix


def _json_default(value: object) -> object:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return str(value)
