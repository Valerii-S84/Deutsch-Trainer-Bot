from __future__ import annotations

import asyncio

from app.catalog.service import LocalCatalogQuizService
from app.config import clear_settings_cache
from app.quiz_bank.schemas import (
    QuizAnswerOption,
    QuizCorrectAnswerReference,
    QuizItem,
    QuizQuestionsResponse,
)
from app.services.training_session import TrainingSessionService
from tests.fakes.training_session import (
    FakeAnalyticsRepository,
    FakeAnswerRepository,
    FakeDatabaseSession,
    FakeOutboxRepository,
    FakeQuestionReferenceRepository,
    FakeSessionItemRepository,
    FakeSessionRepository,
    FakeUserRepository,
)


def test_training_question_flow_uses_local_catalog_service(monkeypatch) -> None:
    monkeypatch.setenv("ACTIVE_CATALOG_ID", "cat-local")
    clear_settings_cache()

    try:
        fake_catalog = FakeLocalCatalogService()
        question, answer_repo = asyncio.run(_run_training_round(fake_catalog))

        assert fake_catalog.calls == [{"catalog_id": "cat-local", "level": "A1", "theme": "T01"}]
        assert question.metadata_snapshot["catalog_id"] == "cat-local"
        assert answer_repo._answers[0].catalog_id == "cat-local"
        assert answer_repo._answers[0].item_id == "local-q1"
        assert answer_repo._answers[0].item_version == "1.0"
    finally:
        clear_settings_cache()


async def _run_training_round(fake_catalog: "FakeLocalCatalogService"):
    answer_repo = FakeAnswerRepository()
    service = TrainingSessionService(
        user_repo=FakeUserRepository(),
        session_repo=FakeSessionRepository(),
        answer_repo=answer_repo,
        analytics_repo=FakeAnalyticsRepository(),
        question_reference_repo=FakeQuestionReferenceRepository(),
        session_item_repo=FakeSessionItemRepository(),
        quiz_service=fake_catalog,
        outbox_repo=FakeOutboxRepository(),
    )
    db = FakeDatabaseSession()
    await service.start_session(db, telegram_user_id=501, level="A1", theme="T01", total_questions=1, force_new=False)
    question = await service.get_or_create_current_question(db, telegram_user_id=501, force_refresh=True)
    await service.submit_answer(db, 501, question.session_id, question.question_token, question.correct_answer)
    return question, answer_repo


class FakeLocalCatalogService(LocalCatalogQuizService):
    def __init__(self) -> None:
        self.calls: list[dict[str, str | None]] = []

    async def catalog_version(self, db, *, catalog_id: str | None = None) -> str | None:
        return "2026-06-30"

    async def get_availability(self, db, *, catalog_id: str | None, level: str, theme: str):
        return type("Availability", (), {"available_items_count": 1})()

    async def request_quiz(
        self,
        db,
        *,
        catalog_id: str | None,
        level: str,
        theme: str | None,
        limit: int,
        user_context,
        seed_material: str,
    ) -> QuizQuestionsResponse:
        self.calls.append({"catalog_id": catalog_id, "level": level, "theme": theme})
        return QuizQuestionsResponse(items=[_local_quiz_item(catalog_id or "")], requested_count=limit, returned_count=1)


def _local_quiz_item(catalog_id: str) -> QuizItem:
    return QuizItem(
        item_id="local-q1",
        level="A1",
        theme="identity",
        theme_key="T01",
        question_text="Was passt?",
        answer_options=[
            QuizAnswerOption(option_id="0", text="Hallo", order=1),
            QuizAnswerOption(option_id="1", text="Tschuess", order=2),
        ],
        correct_answer=QuizCorrectAnswerReference(option_id="0"),
        explanation="Richtig erklärt.",
        metadata={"catalog_id": catalog_id, "item_version": "1.0", "progress_theme_key": "identity"},
        content_version="1.0",
    )
