from __future__ import annotations

from typing import Any

import pytest

from app.quiz_bank import QuizBankRequestContext, QuizBankService
from app.quiz_bank.errors import QuizBankError, QuizBankValidationError


class StubQuizBankClient:
    def __init__(self, payloads: list[dict[str, Any] | Exception]) -> None:
        self._payloads = payloads
        self.calls: list[dict[str, Any]] = []

    def _pop_payload(self) -> dict[str, Any]:
        payload = self._payloads.pop(0)
        if isinstance(payload, Exception):
            raise payload
        return payload

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
        return self._pop_payload()

    async def fetch_health(self) -> dict[str, Any]:
        self.calls.append({"endpoint": "health"})
        return self._pop_payload()

    async def fetch_levels(self) -> dict[str, Any]:
        self.calls.append({"endpoint": "levels"})
        return self._pop_payload()

    async def fetch_themes(
        self,
        *,
        level: str,
        include_counts: bool = True,
        active_only: bool = True,
    ) -> dict[str, Any]:
        self.calls.append(
            {
                "endpoint": "themes",
                "level": level,
                "include_counts": include_counts,
                "active_only": active_only,
            },
        )
        return self._pop_payload()

    async def fetch_availability(self, *, level: str, theme: str) -> dict[str, Any]:
        self.calls.append({"endpoint": "availability", "level": level, "theme": theme})
        return self._pop_payload()

    async def fetch_question(self, *, item_id: str) -> dict[str, Any]:
        self.calls.append({"endpoint": "question", "item_id": item_id})
        return self._pop_payload()

    async def fetch_metadata(self) -> dict[str, Any]:
        self.calls.append({"endpoint": "metadata"})
        return self._pop_payload()


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


@pytest.mark.asyncio
async def test_service_get_levels_filters_unknown_and_inactive_levels_and_caches() -> None:
    stub_client = StubQuizBankClient(
        [
            {
                "levels": [
                    {"code": "A1", "display_name": "A1", "is_active": True},
                    {"code": "A2", "display_name": "A2", "is_active": False},
                    {"code": "C2", "display_name": "C2", "is_active": True},
                ],
                "content_version": "v1",
            }
        ],
    )
    service = QuizBankService(client=stub_client)

    first = await service.get_levels()
    second = await service.get_levels()

    assert [level.code for level in first.levels] == ["A1"]
    assert second.levels == first.levels
    assert [call["endpoint"] for call in stub_client.calls] == ["levels"]


@pytest.mark.asyncio
async def test_service_get_themes_filters_inactive_or_empty_themes() -> None:
    stub_client = StubQuizBankClient(
        [
            {
                "level": "A1",
                "themes": [
                    {
                        "theme": "Artikel",
                        "theme_key": "artikel",
                        "available_items_count": 5,
                        "is_active": True,
                    },
                    {
                        "theme": "Leere Thema",
                        "theme_key": "leer",
                        "available_items_count": 0,
                        "is_active": True,
                    },
                    {
                        "theme": "Alt",
                        "theme_key": "alt",
                        "available_items_count": 5,
                        "is_active": False,
                    },
                ],
            }
        ],
    )
    service = QuizBankService(client=stub_client)

    response = await service.get_themes(level="A1")

    assert [theme.theme_key for theme in response.themes] == ["artikel"]
    assert stub_client.calls[0]["include_counts"] is True
    assert stub_client.calls[0]["active_only"] is True


@pytest.mark.asyncio
async def test_service_get_question_rejects_inactive_lookup() -> None:
    payload = {
        "item_id": "itm-1",
        "level": "A1",
        "theme": "Artikel",
        "question_text": "Was ist korrekt?",
        "answer_options": [
            {"option_id": "o1", "text": "A"},
            {"option_id": "o2", "text": "B"},
        ],
        "correct_answer": "o1",
        "explanation": "Richtig.",
        "metadata": {"progress_theme_key": "artikel"},
        "is_active": False,
    }
    service = QuizBankService(client=StubQuizBankClient([payload]))

    with pytest.raises(QuizBankValidationError):
        await service.get_question(item_id="itm-1")


@pytest.mark.asyncio
async def test_service_validates_health_availability_and_metadata() -> None:
    stub_client = StubQuizBankClient(
        [
            {
                "status": "ok",
                "service": "quiz-bank",
                "checked_at": "2026-05-14T10:00:00Z",
            },
            {
                "level": "A1",
                "theme": "Artikel",
                "theme_key": "artikel",
                "available_items_count": 8,
                "generated_at": "2026-05-14T10:00:00Z",
            },
            {
                "levels": ["A1"],
                "themes": ["Artikel"],
                "metadata_version": "v1",
                "generated_at": "2026-05-14T10:00:00Z",
            },
        ],
    )
    service = QuizBankService(client=stub_client)

    health = await service.get_health()
    availability = await service.get_availability(level="A1", theme="Artikel")
    metadata = await service.get_metadata()
    cached_metadata = await service.get_metadata()

    assert health.status == "ok"
    assert availability.available_items_count == 8
    assert metadata.metadata_version == "v1"
    assert cached_metadata is metadata
    assert [call["endpoint"] for call in stub_client.calls] == ["health", "availability", "metadata"]


@pytest.mark.asyncio
async def test_service_falls_back_to_theme_catalog_when_availability_endpoint_is_missing() -> None:
    stub_client = StubQuizBankClient(
        [
            QuizBankError("not found", status_code=404, endpoint="/availability"),
            {
                "level": "A1",
                "themes": [
                    {
                        "theme": "Person / Identität / Familie",
                        "theme_key": "T01",
                        "available_items_count": 5,
                        "is_active": True,
                    },
                ],
            },
        ],
    )
    service = QuizBankService(client=stub_client)

    availability = await service.get_availability(level="A1", theme="T01")

    assert availability.available_items_count == 5
    assert availability.theme_key == "T01"
    assert [call["endpoint"] for call in stub_client.calls] == ["availability", "themes"]
