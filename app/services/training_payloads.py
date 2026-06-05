from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha1
from typing import Any

from app.quiz_bank.schemas import QuizItem


@dataclass(frozen=True)
class QuizQuestionPayload:
    session_id: int
    question_token: str
    question_id: str
    question_text: str
    answer_options: tuple[tuple[str, str], ...]
    correct_answer: str
    explanation: str | None
    position: int
    total_questions: int
    level: str
    theme: str | None
    correct_answer_text: str | None = None
    theme_key: str | None = None
    content_version: str | None = None
    metadata_snapshot: dict[str, Any] | None = None
    question_reference_id: int | None = None
    training_session_item_id: int | None = None


@dataclass(frozen=True)
class AnswerResult:
    selected_answer: str
    correct_answer: str
    question_token: str
    is_correct: bool
    is_duplicate: bool
    is_completed: bool
    explanation: str | None
    correct_answers: int
    total_questions: int
    session_id: int
    correct_answer_text: str | None = None
    weak_theme: str | None = None
    new_mistakes_count: int = 0
    recommendation_text: str | None = None


class TrainingFlowError(Exception):
    """Base error for the training flow."""


class ActiveSessionConflictError(TrainingFlowError):
    """Raised when an active session already exists."""


class ActiveSessionNotFoundError(TrainingFlowError):
    """Raised when an active session does not exist for the user."""


class QuestionStateError(TrainingFlowError):
    """Raised when pending question state is missing or invalid."""


class NoMoreQuestionsError(TrainingFlowError):
    """Raised when the Quiz Bank returns no available questions."""


class NoReviewItemsError(TrainingFlowError):
    """Raised when review flow has no active mistake items."""


def normalize_text(value: str | None) -> str:
    return (value or "").strip()


def normalize_explanation(explanation: str | Any | None) -> str | None:
    if explanation is None:
        return None
    if hasattr(explanation, "text"):
        return normalize_text(getattr(explanation, "text", ""))
    return normalize_text(str(explanation)) or None


def answer_text(question: QuizItem, option_id: str) -> str:
    for option in question.answer_options:
        if option.option_id == option_id:
            return normalize_text(option.text)
    return option_id


def option_text(payload: QuizQuestionPayload, option_id: str) -> str:
    for candidate_id, candidate_text in payload.answer_options:
        if candidate_id == option_id:
            return candidate_text
    return option_id


def option_ids(payload: QuizQuestionPayload) -> set[str]:
    return {option_id for option_id, _ in payload.answer_options}


def question_metadata_snapshot(question: QuizItem) -> dict[str, Any]:
    metadata = dict(question.metadata)
    metadata["content_version"] = question.content_version
    if question.theme_key:
        metadata["theme_key"] = question.theme_key
    if question.source_metadata is not None:
        metadata["source_metadata"] = question.source_metadata.model_dump(exclude_none=True)
    return {key: value for key, value in metadata.items() if value is not None}


def build_question_payload(
    session_id: int,
    question: QuizItem,
    *,
    position: int,
    total_questions: int,
    question_reference_id: int | None = None,
    training_session_item_id: int | None = None,
    metadata_snapshot: dict[str, Any] | None = None,
) -> QuizQuestionPayload:
    return QuizQuestionPayload(
        session_id=session_id,
        question_token=sha1(question.item_id.encode("utf-8"), usedforsecurity=False).hexdigest()[:8],
        question_id=question.item_id,
        question_text=normalize_text(question.question_text),
        answer_options=tuple((item.option_id, normalize_text(item.text)) for item in question.answer_options),
        correct_answer=question.correct_answer.option_id,
        explanation=normalize_explanation(question.explanation),
        position=position,
        total_questions=total_questions,
        level=question.level,
        theme=question.theme,
        correct_answer_text=answer_text(question, question.correct_answer.option_id),
        theme_key=question.theme_key,
        content_version=question.content_version,
        metadata_snapshot=metadata_snapshot or question_metadata_snapshot(question),
        question_reference_id=question_reference_id,
        training_session_item_id=training_session_item_id,
    )


def serialize_question_payload(payload: QuizQuestionPayload) -> dict[str, object]:
    return {
        "session_id": payload.session_id,
        "question_token": payload.question_token,
        "question_id": payload.question_id,
        "question_text": payload.question_text,
        "answer_options": [{"option_id": option_id, "text": text} for option_id, text in payload.answer_options],
        "correct_answer": payload.correct_answer,
        "explanation": payload.explanation,
        "position": payload.position,
        "total_questions": payload.total_questions,
        "level": payload.level,
        "theme": payload.theme,
        "correct_answer_text": payload.correct_answer_text,
        "theme_key": payload.theme_key,
        "content_version": payload.content_version,
        "metadata_snapshot": payload.metadata_snapshot,
        "question_reference_id": payload.question_reference_id,
        "training_session_item_id": payload.training_session_item_id,
    }


def deserialize_question_payload(payload: dict[str, object]) -> QuizQuestionPayload:
    options = _deserialize_options(payload.get("answer_options"))
    try:
        return QuizQuestionPayload(
            session_id=int(payload["session_id"]),
            question_token=str(payload["question_token"]),
            question_id=str(payload["question_id"]),
            question_text=str(payload["question_text"]),
            answer_options=tuple(options),
            correct_answer=str(payload["correct_answer"]),
            explanation=payload.get("explanation") if isinstance(payload.get("explanation"), str) else None,
            position=int(payload["position"]),
            total_questions=int(payload["total_questions"]),
            level=str(payload["level"]),
            theme=str(payload["theme"]) if payload.get("theme") is not None else None,
            correct_answer_text=payload.get("correct_answer_text")
            if isinstance(payload.get("correct_answer_text"), str)
            else None,
            theme_key=payload.get("theme_key") if isinstance(payload.get("theme_key"), str) else None,
            content_version=payload.get("content_version") if isinstance(payload.get("content_version"), str) else None,
            metadata_snapshot=payload.get("metadata_snapshot")
            if isinstance(payload.get("metadata_snapshot"), dict)
            else None,
            question_reference_id=int(payload["question_reference_id"])
            if payload.get("question_reference_id") is not None
            else None,
            training_session_item_id=int(payload["training_session_item_id"])
            if payload.get("training_session_item_id") is not None
            else None,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise QuestionStateError("pending question payload is invalid") from exc


def _deserialize_options(options_raw: object) -> list[tuple[str, str]]:
    if not isinstance(options_raw, list):
        raise QuestionStateError("pending question payload is missing options")

    options: list[tuple[str, str]] = []
    for option in options_raw:
        if not isinstance(option, dict):
            raise QuestionStateError("invalid option payload")
        option_id = option.get("option_id")
        text = option.get("text")
        if not isinstance(option_id, str) or not isinstance(text, str):
            raise QuestionStateError("invalid option payload")
        options.append((option_id, text))
    return options
