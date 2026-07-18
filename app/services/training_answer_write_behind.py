from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from app.runtime.answer_persistence_queue import AnswerPersistEnqueueItem, AnswerPersistenceQueue
from app.services.training_answer_cache import (
    get_cached_pending_question_if_enabled,
    get_cached_pending_questions_if_enabled,
)
from app.services.training_payloads import AnswerResult, QuestionStateError, QuizQuestionPayload, option_ids, option_text


ANSWER_ACCEPTED_EVENT = "answer.accepted"
PAYLOAD_VERSION = 1


@dataclass(frozen=True, slots=True)
class AnswerWriteBehindRequest:
    telegram_user_id: int
    session_id: int
    question_token: str
    selected_option_id: str
    telegram_update_id: int | None
    callback_query_id: str | None


async def accept_answer_write_behind(
    *,
    queue: AnswerPersistenceQueue,
    telegram_user_id: int,
    session_id: int,
    question_token: str,
    selected_option_id: str,
    telegram_update_id: int | None,
    callback_query_id: str | None,
) -> AnswerResult:
    pending = await get_cached_pending_question_if_enabled(
        session_id=session_id,
        question_token=question_token,
    )
    if pending is None:
        raise QuestionStateError("No active question in answer cache")
    _validate_pending(pending, telegram_user_id=telegram_user_id, selected_option_id=selected_option_id)

    result = _answer_result(pending, selected_option_id=selected_option_id)
    answer_event_id = _answer_event_id(telegram_update_id=telegram_update_id, callback_query_id=callback_query_id)
    enqueue_result = await queue.enqueue_answer_event(
        answer_event_id=answer_event_id,
        question_dedupe_id=f"{session_id}:{question_token}",
        event_payload=_answer_event_payload(
            pending,
            result,
            selected_option_id=selected_option_id,
            telegram_update_id=telegram_update_id,
            callback_query_id=callback_query_id,
            answer_event_id=answer_event_id,
        ),
        result_payload=asdict(result),
    )
    if not enqueue_result.duplicate:
        return result
    return _duplicate_result(enqueue_result.result_payload)


async def accept_answer_write_behind_many(
    *,
    queue: AnswerPersistenceQueue,
    requests: list[AnswerWriteBehindRequest],
) -> list[AnswerResult | Exception]:
    if not requests:
        return []
    pending_items = await get_cached_pending_questions_if_enabled(
        [(request.session_id, request.question_token) for request in requests],
    )
    results: list[AnswerResult | Exception | None] = [None] * len(requests)
    enqueue_items: list[tuple[int, AnswerPersistEnqueueItem, AnswerResult]] = []

    for index, (request, pending) in enumerate(zip(requests, pending_items)):
        try:
            if pending is None:
                raise QuestionStateError("No active question in answer cache")
            item, result = _prepare_answer_enqueue_item(request, pending)
        except Exception as exc:
            results[index] = exc
            continue
        enqueue_items.append((index, item, result))

    if enqueue_items:
        enqueue_results = await queue.enqueue_answer_events([item for _index, item, _result in enqueue_items])
        for (index, _item, result), enqueue_result in zip(enqueue_items, enqueue_results):
            results[index] = result if not enqueue_result.duplicate else _duplicate_result(enqueue_result.result_payload)

    return [
        result if result is not None else QuestionStateError("Answer write-behind result missing")
        for result in results
    ]


def _prepare_answer_enqueue_item(
    request: AnswerWriteBehindRequest,
    pending: QuizQuestionPayload,
) -> tuple[AnswerPersistEnqueueItem, AnswerResult]:
    _validate_pending(
        pending,
        telegram_user_id=request.telegram_user_id,
        selected_option_id=request.selected_option_id,
    )
    result = _answer_result(pending, selected_option_id=request.selected_option_id)
    answer_event_id = _answer_event_id(
        telegram_update_id=request.telegram_update_id,
        callback_query_id=request.callback_query_id,
    )
    return (
        AnswerPersistEnqueueItem(
            answer_event_id=answer_event_id,
            question_dedupe_id=f"{request.session_id}:{request.question_token}",
            event_payload=_answer_event_payload(
                pending,
                result,
                selected_option_id=request.selected_option_id,
                telegram_update_id=request.telegram_update_id,
                callback_query_id=request.callback_query_id,
                answer_event_id=answer_event_id,
            ),
            result_payload=asdict(result),
        ),
        result,
    )


def _validate_pending(
    pending: QuizQuestionPayload,
    *,
    telegram_user_id: int,
    selected_option_id: str,
) -> None:
    if pending.telegram_user_id is not None and int(pending.telegram_user_id) != telegram_user_id:
        raise QuestionStateError("Question token belongs to another user")
    if pending.user_id is None:
        raise QuestionStateError("Cached answer state is missing user id")
    if selected_option_id not in option_ids(pending):
        raise QuestionStateError("Selected answer is invalid")


def _answer_result(pending: QuizQuestionPayload, *, selected_option_id: str) -> AnswerResult:
    is_correct = selected_option_id == pending.correct_answer
    previous_answered = _previous_answered_count(pending)
    previous_correct = _previous_correct_answers(pending)
    answered_count = min(pending.total_questions, previous_answered + 1)
    correct_answers = min(pending.total_questions, previous_correct + (1 if is_correct else 0))
    completed = answered_count >= pending.total_questions
    return AnswerResult(
        selected_answer=selected_option_id,
        correct_answer=pending.correct_answer,
        question_token=pending.question_token,
        is_correct=is_correct,
        is_duplicate=False,
        is_completed=completed,
        explanation=pending.explanation,
        correct_answers=correct_answers,
        total_questions=pending.total_questions,
        session_id=pending.session_id,
        correct_answer_text=pending.correct_answer_text or option_text(pending, pending.correct_answer),
        weak_theme=None,
        new_mistakes_count=0,
        recommendation_text="Starte eine neue Runde, um weiter zu üben." if completed else None,
    )


def _answer_event_payload(
    pending: QuizQuestionPayload,
    result: AnswerResult,
    *,
    selected_option_id: str,
    telegram_update_id: int | None,
    callback_query_id: str | None,
    answer_event_id: str,
) -> dict[str, Any]:
    user_id = pending.user_id
    if user_id is None:
        raise QuestionStateError("Cached answer state is missing user id")
    return {
        "payload_version": PAYLOAD_VERSION,
        "event_type": ANSWER_ACCEPTED_EVENT,
        "answer_event_id": answer_event_id,
        "telegram_update_id": telegram_update_id,
        "callback_query_id": callback_query_id,
        "telegram_user_id": pending.telegram_user_id,
        "user_id": user_id,
        "session_id": pending.session_id,
        "session_item_id": pending.training_session_item_id,
        "question_reference_id": pending.question_reference_id,
        "question_token": pending.question_token,
        "catalog_id": _catalog_id(pending.metadata_snapshot),
        "item_id": pending.question_id,
        "item_version": pending.content_version,
        "level": pending.level,
        "theme": pending.theme,
        "theme_id": _theme_id(pending),
        "theme_key": pending.theme_key,
        "selected_answer": selected_option_id,
        "correct_answer": pending.correct_answer,
        "is_correct": result.is_correct,
        "session_type": pending.session_type or "regular",
        "position": pending.position,
        "available_items_count": _available_count(pending.metadata_snapshot),
        "metadata_snapshot": pending.metadata_snapshot,
        "session_completed": result.is_completed,
        "answered_count": result.total_questions if result.is_completed else _previous_answered_count(pending) + 1,
        "correct_answers": result.correct_answers,
        "total_questions": result.total_questions,
        "result": asdict(result),
    }


def _duplicate_result(payload: dict[str, Any]) -> AnswerResult:
    result = AnswerResult(
        selected_answer=str(payload["selected_answer"]),
        correct_answer=str(payload["correct_answer"]),
        question_token=str(payload["question_token"]),
        is_correct=bool(payload["is_correct"]),
        is_duplicate=True,
        is_completed=bool(payload["is_completed"]),
        explanation=payload.get("explanation") if isinstance(payload.get("explanation"), str) else None,
        correct_answers=int(payload["correct_answers"]),
        total_questions=int(payload["total_questions"]),
        session_id=int(payload["session_id"]),
        correct_answer_text=payload.get("correct_answer_text")
        if isinstance(payload.get("correct_answer_text"), str)
        else None,
        weak_theme=payload.get("weak_theme") if isinstance(payload.get("weak_theme"), str) else None,
        new_mistakes_count=int(payload.get("new_mistakes_count") or 0),
        recommendation_text=payload.get("recommendation_text")
        if isinstance(payload.get("recommendation_text"), str)
        else None,
    )
    return result


def _answer_event_id(*, telegram_update_id: int | None, callback_query_id: str | None) -> str:
    if telegram_update_id is not None:
        return f"update:{telegram_update_id}"
    if callback_query_id:
        return f"callback:{callback_query_id}"
    raise QuestionStateError("Answer idempotency key is unavailable")


def _previous_answered_count(pending: QuizQuestionPayload) -> int:
    if pending.answered_count is not None:
        return max(0, int(pending.answered_count))
    return max(0, pending.position - 1)


def _previous_correct_answers(pending: QuizQuestionPayload) -> int:
    if pending.correct_answers is not None:
        return max(0, int(pending.correct_answers))
    return 0


def _catalog_id(metadata_snapshot: dict[str, object] | None) -> str | None:
    value = (metadata_snapshot or {}).get("catalog_id")
    return value if isinstance(value, str) and value else None


def _theme_id(pending: QuizQuestionPayload) -> str | None:
    metadata = pending.metadata_snapshot or {}
    value = metadata.get("theme_id")
    if isinstance(value, str) and value:
        return value
    return pending.theme_key


def _available_count(metadata_snapshot: dict[str, object] | None) -> int | None:
    value = (metadata_snapshot or {}).get("available_items_count")
    return value if isinstance(value, int) and value >= 0 else None
