"""Quiz Bank response normalization and domain helpers."""

from __future__ import annotations

from collections.abc import Mapping
from hashlib import sha256
from typing import Any

from .errors import QuizBankValidationError


def data_items(payload: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    data = payload.get("data")
    if not isinstance(data, list):
        return []
    return [item for item in data if isinstance(item, Mapping)]


def normalize_levels_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    levels = []
    for item in data_items(payload):
        code = str(item.get("cefr_level") or item.get("code") or "").strip().upper()
        if not code:
            continue
        status = str(item.get("status") or "active").strip().lower()
        levels.append({"code": code, "display_name": code, "is_active": status == "active"})
    return {"levels": levels}


def normalize_themes_payload(
    payload: Mapping[str, Any],
    *,
    level: str,
    include_counts: bool,
    active_only: bool,
) -> dict[str, Any]:
    themes = []
    for item in data_items(payload):
        status = str(item.get("status") or "active").strip().lower()
        if active_only and status != "active":
            continue
        theme_id = str(item.get("theme_id") or item.get("topic_id") or "").strip()
        title = str(item.get("title") or "").strip()
        if not theme_id or not title:
            continue
        themes.append(
            {
                "theme": title,
                "theme_key": theme_id,
                "available_items_count": 1 if include_counts and status == "active" else None,
                "is_active": status == "active",
                "metadata": {"theme_id": theme_id},
            }
        )
    return {"level": level.strip().upper(), "themes": themes}


def looks_like_theme_id(value: str) -> bool:
    return len(value) == 3 and value[0].upper() == "T" and value[1:].isdigit()


def normalize_key(value: str) -> str:
    return " ".join(value.casefold().strip().split())


def quota_scope_key(
    level: str,
    theme: str | None,
    user_context: Mapping[str, Any] | None,
) -> str:
    context = user_context or {}
    parts = [
        "dtb",
        str(context.get("session_type") or "regular"),
        str(context.get("target_level") or level),
        str(theme or "all"),
    ]
    raw = ":".join(parts)
    digest = sha256(raw.encode("utf-8")).hexdigest()[:16]
    return f"dtb:{digest}"


def normalize_next_quiz_response(
    payload: Mapping[str, Any],
    *,
    requested_count: int,
) -> dict[str, Any]:
    return {
        "items": [normalize_quiz_item_response(payload)],
        "requested_count": requested_count,
        "returned_count": 1,
        "has_more": False,
    }


def normalize_quiz_item_response(payload: Mapping[str, Any]) -> dict[str, Any]:
    quiz_item = payload.get("quiz_item")
    if not isinstance(quiz_item, Mapping):
        raise QuizBankValidationError("Quiz Bank response is missing quiz_item")

    feedback = quiz_item.get("feedback")
    if not isinstance(feedback, Mapping):
        raise QuizBankValidationError("Quiz Bank response is missing answer feedback")

    correct_answer = str(feedback.get("correctAnswerId") or "").strip()
    if not correct_answer:
        raise QuizBankValidationError("Quiz Bank response is missing correct answer")

    question_text = _question_text(quiz_item)
    theme_title, theme_key = _theme_fields(quiz_item)
    metadata = _metadata_with_progress_key(quiz_item, theme_title, theme_key)
    return {
        "item_id": str(quiz_item.get("id") or quiz_item.get("public_id") or "").strip(),
        "level": str(quiz_item.get("cefr_level") or "").strip().upper(),
        "theme": theme_title,
        "theme_key": theme_key,
        "question_text": question_text,
        "answer_options": _answer_options(quiz_item),
        "correct_answer": {"option_id": correct_answer},
        "explanation": {"text": str(feedback.get("explanation") or "").strip() or "Keine Erklärung verfügbar."},
        "metadata": metadata,
        "source_metadata": {
            "source": "quiz_bank_api",
            "source_metadata": {
                "delivery_id": payload.get("delivery_id"),
                "consumer_id": payload.get("consumer_id"),
            },
        },
    }


def _question_text(quiz_item: Mapping[str, Any]) -> str:
    question = quiz_item.get("question")
    question_text = str(question.get("text") or "").strip() if isinstance(question, Mapping) else ""
    if not question_text:
        raise QuizBankValidationError("Quiz Bank response is missing question text")
    return question_text


def _theme_fields(quiz_item: Mapping[str, Any]) -> tuple[str, str | None]:
    theme = quiz_item.get("theme")
    if not isinstance(theme, Mapping):
        return "", None
    return str(theme.get("title") or "").strip(), str(theme.get("slug") or "").strip() or None


def _answer_options(quiz_item: Mapping[str, Any]) -> list[dict[str, Any]]:
    options = []
    raw_options = quiz_item.get("options")
    if not isinstance(raw_options, list):
        return options
    for option in raw_options:
        if not isinstance(option, Mapping):
            continue
        option_id = str(option.get("id") or "").strip()
        text = str(option.get("text") or "").strip()
        if not option_id or not text:
            continue
        order = option.get("position") if isinstance(option.get("position"), int) else None
        options.append({"option_id": option_id, "text": text, "order": order})
    return options


def _metadata_with_progress_key(
    quiz_item: Mapping[str, Any],
    theme_title: str,
    theme_key: str | None,
) -> dict[str, Any]:
    metadata = quiz_item.get("metadata")
    if not isinstance(metadata, dict):
        metadata = {}
    progress_theme_key = theme_key or normalize_key(theme_title).replace(" ", "-") or "unknown"
    return {**metadata, "progress_theme_key": progress_theme_key}
