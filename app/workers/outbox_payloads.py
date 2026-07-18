from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class AnswerAcceptedPayload:
    telegram_user_id: int
    user_id: int
    session_id: int
    answer_id: int
    session_item_id: int | None
    level: str
    theme: str | None
    theme_id: str | None
    theme_key: str | None
    catalog_id: str | None
    item_id: str
    item_version: str | None
    selected_answer: str
    correct_answer: str
    is_correct: bool
    session_type: str
    answered_at: datetime | None
    metadata_snapshot: dict[str, object] | None
    available_items_count: int | None
    question_token: str | None
    position: int | None
    session_completed: bool
    answered_count: int | None
    correct_answers: int | None
    total_questions: int | None


def parse_answer_accepted_payload(payload: dict[str, object]) -> AnswerAcceptedPayload:
    theme_key = _optional_str(payload, "theme_key")
    theme_id = _optional_str(payload, "theme_id") or theme_key
    session_item_id = _optional_int(payload, "session_item_id")
    if session_item_id is None:
        session_item_id = _optional_int(payload, "training_session_item_id")
    return AnswerAcceptedPayload(
        telegram_user_id=_required_int(payload, "telegram_user_id"),
        user_id=_required_int(payload, "user_id"),
        session_id=_required_int(payload, "session_id"),
        answer_id=_required_int(payload, "answer_id"),
        session_item_id=session_item_id,
        level=_required_str(payload, "level"),
        theme=_optional_str(payload, "theme"),
        theme_id=theme_id,
        theme_key=theme_key or theme_id,
        catalog_id=_optional_str(payload, "catalog_id"),
        item_id=_required_str(payload, "item_id"),
        item_version=_optional_str(payload, "item_version"),
        selected_answer=_required_str(payload, "selected_answer"),
        correct_answer=_required_str(payload, "correct_answer"),
        is_correct=_required_bool(payload, "is_correct"),
        session_type=_required_str(payload, "session_type"),
        answered_at=_optional_datetime(payload, "answered_at"),
        metadata_snapshot=_optional_dict(payload, "metadata_snapshot"),
        available_items_count=_optional_int(payload, "available_items_count"),
        question_token=_optional_str(payload, "question_token"),
        position=_optional_int(payload, "position"),
        session_completed=_required_bool(payload, "session_completed"),
        answered_count=_optional_int(payload, "answered_count"),
        correct_answers=_optional_int(payload, "correct_answers"),
        total_questions=_optional_int(payload, "total_questions"),
    )


def _required_int(payload: dict[str, object], key: str) -> int:
    value = payload.get(key)
    if not isinstance(value, int):
        raise ValueError(f"Outbox payload field must be int: {key}")
    return value


def _optional_int(payload: dict[str, object], key: str) -> int | None:
    value = payload.get(key)
    return value if isinstance(value, int) else None


def _required_str(payload: dict[str, object], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"Outbox payload field must be non-empty string: {key}")
    return value


def _optional_str(payload: dict[str, object], key: str) -> str | None:
    value = payload.get(key)
    return value if isinstance(value, str) and value else None


def _required_bool(payload: dict[str, object], key: str) -> bool:
    value = payload.get(key)
    if not isinstance(value, bool):
        raise ValueError(f"Outbox payload field must be bool: {key}")
    return value


def _optional_dict(payload: dict[str, object], key: str) -> dict[str, object] | None:
    value = payload.get(key)
    return value if isinstance(value, dict) else None


def _optional_datetime(payload: dict[str, object], key: str) -> datetime | None:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"Outbox payload field must be ISO datetime string: {key}") from exc
