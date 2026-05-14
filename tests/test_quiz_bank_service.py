from __future__ import annotations

from typing import Any

import pytest

from app.quiz_bank import QuizBankRequestContext, QuizBankService
from app.quiz_bank.errors import QuizBankValidationError


class StubQuizBankClient:
    def __init__(self, payloads: list[dict[str, Any]]) -> None:
        self._payloads = payloads
        self.calls: list[dict[str, Any]] = []

    async def fetch_questions(
        self,
        *,
        level: str,
        theme: str | None,
        limit: int,
        user_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.calls.append(
            {
                "level": level,
                "theme": theme,
                "limit": limit,
                "user_context": user_context or {},
            },
        )
        payload = self._payloads.pop(0)
        return payload


@pytest.mark.asyncio
async def test_service_request_quiz_returns_valid_batch() -> None:
    payload = {
        "items": [
            {
                "item_id": "itm-1",
                "level": "A1",
                "theme": "Artikel",
                "question_text": "Was ist korrekt?",
                "answer_options": [
                    {"option_id": "o1", "text": "A"},
                    {"option_id": "o2", "text": "B"},
                ],
                "correct_answer": {"option_id": "o1"},
                "explanation": {"text": "Richtig."},
                "metadata": {"progress_theme_key": "artikel"},
                "source_metadata": {"source": "quiz_bank_api"},
            }
        ],
        "requested_count": 1,
        "returned_count": 1,
        "has_more": False,
    }

    context = QuizBankRequestContext(
        seen_item_ids=["prev-1"],
        session_type="regular",
    )
    stub_client = StubQuizBankClient([payload])
    service = QuizBankService(client=stub_client)

    response = await service.request_quiz(level="A1", theme="Artikel", limit=1, user_context=context)
    assert response.requested_count == 1

    call = stub_client.calls[0]
    assert call["level"] == "A1"
    assert call["theme"] == "Artikel"
    assert call["limit"] == 1
    assert call["user_context"]["session_type"] == "regular"


@pytest.mark.asyncio
async def test_service_request_quiz_defaults_limit_to_one() -> None:
    payload = {
        "items": [
            {
                "item_id": "itm-1",
                "level": "A1",
                "theme": "Artikel",
                "question_text": "Was ist korrekt?",
                "answer_options": [
                    {"option_id": "o1", "text": "A"},
                    {"option_id": "o2", "text": "B"},
                ],
                "correct_answer": {"option_id": "o1"},
                "explanation": "Richtig.",
                "metadata": {"progress_theme_key": "artikel"},
            }
        ],
        "requested_count": 1,
        "returned_count": 1,
        "has_more": False,
    }
    stub_client = StubQuizBankClient([payload])
    service = QuizBankService(client=stub_client)

    await service.request_quiz(level="A1", theme="Artikel", user_context=None)

    assert stub_client.calls[0]["limit"] == 1


@pytest.mark.asyncio
async def test_service_request_quiz_rejects_invalid_payload() -> None:
    invalid_payload = {
        "items": [
            {
                "item_id": "itm-1",
                "level": "A1",
                "theme": "Artikel",
                "question_text": "Was ist korrekt?",
                "answer_options": [
                    {"option_id": "o1", "text": "A"},
                ],
                "correct_answer": {"option_id": "o1"},
                "explanation": {"text": "Richtig."},
                "metadata": {"progress_theme_key": "artikel"},
            }
        ],
        "requested_count": 1,
        "returned_count": 1,
    }
    service = QuizBankService(
        client=StubQuizBankClient([invalid_payload]),
    )

    with pytest.raises(QuizBankValidationError):
        await service.request_quiz(level="A1", theme="Artikel", limit=1)


@pytest.mark.asyncio
async def test_service_request_quiz_invalid_limit() -> None:
    service = QuizBankService(client=StubQuizBankClient([]))
    with pytest.raises(QuizBankValidationError):
        await service.request_quiz(level="A1", theme="Artikel", limit=0)
