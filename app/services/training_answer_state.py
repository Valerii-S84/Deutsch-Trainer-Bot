from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.services.training_payloads import QuizQuestionPayload


@dataclass(frozen=True)
class AnswerContext:
    user: Any
    session: Any
    pending: QuizQuestionPayload
    selected_option_id: str
    correct_answer_text: str


@dataclass(frozen=True)
class AnswerSnapshot:
    telegram_user_id: int
    user_id: int
    session_id: int
    session_status: str
    session_type: str
    level: str
    theme: str | None
    total_questions: int
    correct_answers: int
    answered_count: int
    pending: QuizQuestionPayload
    selected_option_id: str
    correct_answer_text: str
