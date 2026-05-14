from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

import pytest

from app.quiz_bank import QuizBankRequestContext
from app.quiz_bank.schemas import QuizAnswerOption, QuizCorrectAnswerReference, QuizItem, QuizQuestionsResponse
from app.repositories.quiz_sessions import QuizSessionStatus
from app.services.training_session import NoMoreQuestionsError, TrainingSessionService


@dataclass
class FakeUser:
    id: int
    telegram_user_id: int
    selected_level: str | None = None
    selected_theme: str | None = None


@dataclass
class FakeSession:
    id: int
    user_id: int
    level: str
    theme: str | None
    status: str
    total_questions: int
    correct_answers: int = 0
    shown_questions_count: int = 0
    source_metadata: dict | None = None
    api_metadata: dict | None = None


@dataclass
class FakeAnswer:
    id: int
    session_id: int
    user_id: int
    external_quiz_id: str
    selected_answer: str
    correct_answer: str
    is_correct: bool


@dataclass
class FakeMistake:
    id: int
    level: str
    theme: str
    external_quiz_id: str


@dataclass
class FakeQuestionReference:
    id: int
    item_id: str


@dataclass
class FakeSessionItem:
    id: int
    session_id: int
    user_id: int
    question_reference_id: int
    item_id: str
    position: int
    status: str = "shown"
    shown_at: str | None = "now"
    answered_at: str | None = None
    daily_limit_charged_at: str | None = None


class FakeDatabaseSession:
    def __init__(self) -> None:
        self.flushed = False
        self.rolled_back = False

    async def flush(self) -> None:
        self.flushed = True

    async def rollback(self) -> None:
        self.rolled_back = True


class FakeUserRepository:
    def __init__(self) -> None:
        self._users: dict[int, FakeUser] = {}
        self._next_id = 1

    async def get_by_telegram_id(self, db, telegram_user_id: int) -> FakeUser | None:
        return self._users.get(telegram_user_id)

    async def create_if_missing(self, db, telegram_user_id: int) -> FakeUser:
        user = self._users.get(telegram_user_id)
        if user is None:
            user = FakeUser(id=self._next_id, telegram_user_id=telegram_user_id)
            self._users[telegram_user_id] = user
            self._next_id += 1
        return user

    async def set_training_preferences(
        self,
        db,
        telegram_user_id: int,
        *,
        level: str | None = None,
        theme: str | None = None,
    ) -> FakeUser:
        user = await self.create_if_missing(db, telegram_user_id)
        if level is not None:
            user.selected_level = level
        if theme is not None:
            user.selected_theme = theme
        return user


class FakeSessionRepository:
    def __init__(self) -> None:
        self._sessions: list[FakeSession] = []
        self._next_id = 1

    async def get_active_for_user(self, db, user_id: int) -> FakeSession | None:
        for session in self._sessions:
            if session.user_id == user_id and session.status == QuizSessionStatus.active:
                return session
        return None

    async def get_by_id_for_user(self, db, session_id: int, user_id: int) -> FakeSession | None:
        for session in self._sessions:
            if session.id == session_id and session.user_id == user_id:
                return session
        return None

    async def create(
        self,
        db,
        *,
        user_id: int,
        level: str,
        theme: str | None,
        total_questions: int,
        source: str,
        source_metadata: dict | None = None,
        api_metadata: dict | None = None,
    ) -> FakeSession:
        session = FakeSession(
            id=self._next_id,
            user_id=user_id,
            level=level,
            theme=theme,
            status=QuizSessionStatus.active,
            total_questions=total_questions,
            source_metadata=source_metadata,
            api_metadata=api_metadata or {},
        )
        self._next_id += 1
        self._sessions.append(session)
        return session

    async def set_status(self, db, session: FakeSession, status: str, *, finished_at=None) -> FakeSession:
        session.status = status
        return session

    async def mark_completed(self, db, session: FakeSession, *, finished_at=None) -> FakeSession:
        return await self.set_status(db, session, QuizSessionStatus.completed, finished_at=finished_at)

    async def mark_cancelled(self, db, session: FakeSession, *, finished_at=None) -> FakeSession:
        return await self.set_status(db, session, QuizSessionStatus.cancelled, finished_at=finished_at)

    async def mark_failed(self, db, session: FakeSession, *, finished_at=None) -> FakeSession:
        return await self.set_status(db, session, QuizSessionStatus.failed, finished_at=finished_at)

    async def set_pending_question(self, db, session: FakeSession, question_data: dict) -> FakeSession:
        metadata = dict(session.api_metadata or {})
        metadata["pending_question"] = question_data
        session.api_metadata = metadata
        return session

    async def clear_pending_question(self, db, session: FakeSession) -> FakeSession:
        metadata = dict(session.api_metadata or {})
        metadata.pop("pending_question", None)
        session.api_metadata = metadata
        return session

    async def set_api_metadata(self, db, session: FakeSession, api_metadata: dict | None) -> FakeSession:
        session.api_metadata = api_metadata
        return session

    async def increment_correct_answers(self, db, session: FakeSession, delta: int) -> int:
        session.correct_answers += delta
        return session.correct_answers

    async def increment_shown_questions_count(self, db, session: FakeSession, delta: int) -> int:
        session.shown_questions_count += delta
        return session.shown_questions_count


class FakeAnswerRepository:
    def __init__(self) -> None:
        self._answers: list[FakeAnswer] = []
        self._next_id = 1

    async def create(
        self,
        db,
        *,
        session_id: int,
        user_id: int,
        external_quiz_id: str,
        selected_answer: str,
        correct_answer: str,
        is_correct: bool,
        training_session_item_id: int | None = None,
        question_reference_id: int | None = None,
        quiz_source: str | None = None,
        external_ref: str | None = None,
        level: str | None = None,
        theme: str | None = None,
        theme_key: str | None = None,
        session_type: str = "regular",
        metadata_snapshot: dict[str, object] | None = None,
    ) -> FakeAnswer:
        answer = FakeAnswer(
            id=self._next_id,
            session_id=session_id,
            user_id=user_id,
            external_quiz_id=external_quiz_id,
            selected_answer=selected_answer,
            correct_answer=correct_answer,
            is_correct=is_correct,
        )
        self._next_id += 1
        self._answers.append(answer)
        return answer

    async def get_by_session_and_question(
        self,
        db,
        *,
        session_id: int,
        user_id: int,
        external_quiz_id: str,
    ) -> FakeAnswer | None:
        for answer in self._answers:
            if (
                answer.session_id == session_id
                and answer.user_id == user_id
                and answer.external_quiz_id == external_quiz_id
            ):
                return answer
        return None

    async def count_by_session(self, db, session_id: int) -> int:
        return sum(1 for answer in self._answers if answer.session_id == session_id)

    async def list_question_ids_by_session(self, db, session_id: int) -> list[str]:
        return [
            answer.external_quiz_id
            for answer in self._answers
            if answer.session_id == session_id
        ]


class FakeQuestionReferenceRepository:
    def __init__(self) -> None:
        self._items: dict[str, FakeQuestionReference] = {}
        self._next_id = 1

    async def upsert_snapshot(self, db, *, item_id: str, **kwargs: object) -> FakeQuestionReference:
        existing = self._items.get(item_id)
        if existing is not None:
            return existing
        item = FakeQuestionReference(id=self._next_id, item_id=item_id)
        self._next_id += 1
        self._items[item_id] = item
        return item


class FakeSessionItemRepository:
    def __init__(self) -> None:
        self._items: list[FakeSessionItem] = []
        self._next_id = 1

    async def get_by_session_item(self, db, *, session_id: int, item_id: str) -> FakeSessionItem | None:
        for item in self._items:
            if item.session_id == session_id and item.item_id == item_id:
                return item
        return None

    async def create_shown(
        self,
        db,
        *,
        session_id: int,
        user_id: int,
        question_reference_id: int,
        item_id: str,
        position: int,
    ) -> FakeSessionItem:
        existing = await self.get_by_session_item(db, session_id=session_id, item_id=item_id)
        if existing is not None:
            return existing
        item = FakeSessionItem(
            id=self._next_id,
            session_id=session_id,
            user_id=user_id,
            question_reference_id=question_reference_id,
            item_id=item_id,
            position=position,
        )
        self._next_id += 1
        self._items.append(item)
        return item

    async def mark_answered(self, db, session_item: FakeSessionItem) -> FakeSessionItem:
        session_item.status = "answered"
        session_item.answered_at = "now"
        return session_item

    async def mark_daily_limit_charged(
        self,
        db,
        session_item: FakeSessionItem,
        *,
        daily_limit_id: int | None = None,
    ) -> FakeSessionItem:
        if session_item.shown_at is None:
            raise ValueError("Daily limit can only be charged after an item is shown")
        if session_item.daily_limit_charged_at is None:
            session_item.daily_limit_charged_at = "now"
        if daily_limit_id is not None:
            session_item.daily_limit_id = daily_limit_id
        return session_item


class FakeAnalyticsRepository:
    def __init__(self) -> None:
        self.events: list[SimpleNamespace] = []

    async def record(
        self,
        db,
        *,
        event_name: str,
        user_id: int | None,
        session_id: int | None = None,
        event_metadata: dict | None = None,
        source: str = "bot",
    ) -> SimpleNamespace:
        event = SimpleNamespace(
            id=len(self.events) + 1,
            event_name=event_name,
            user_id=user_id,
            session_id=session_id,
            event_metadata=event_metadata or {},
            source=source,
        )
        self.events.append(event)
        return event


class FakeQuizBankService:
    def __init__(self, responses: list[object]) -> None:
        self._responses = list(responses)

    async def request_quiz(
        self,
        *,
        level: str,
        theme: str | None,
        limit: int,
        user_context: QuizBankRequestContext | None = None,
    ):
        return self._responses.pop(0)


class FakeMistakeService:
    def __init__(self, active_items: list[FakeMistake]) -> None:
        self.active_items = active_items
        self.wrong_calls: list[dict[str, object]] = []
        self.success_calls: list[dict[str, object]] = []
        self.unavailable_calls: list[dict[str, object]] = []

    async def get_review_items(self, db, telegram_user_id: int) -> list[FakeMistake]:
        return self.active_items

    async def record_wrong_answer(self, db, telegram_user_id: int, **kwargs: object) -> None:
        self.wrong_calls.append(kwargs)

    async def record_review_success(self, db, telegram_user_id: int, **kwargs: object) -> None:
        self.success_calls.append(kwargs)

    async def mark_review_items_unavailable(self, db, telegram_user_id: int, **kwargs: object) -> None:
        self.unavailable_calls.append(kwargs)
        unavailable_ids = set(kwargs.get("external_quiz_ids") or [])
        self.active_items = [item for item in self.active_items if item.external_quiz_id not in unavailable_ids]

    async def get_weak_areas(self, db, telegram_user_id: int) -> list[dict[str, object]]:
        return []


def _question_payload(
    item_id: str = "q1",
    correct_answer: str = "a2",
    level: str = "A1",
    theme: str = "Alltag",
) -> QuizQuestionsResponse:
    return QuizQuestionsResponse(
        items=[
            QuizItem(
                item_id=item_id,
                level=level,
                theme=theme,
                question_text="Was ist korrekt?",
                answer_options=[
                    QuizAnswerOption(option_id="a1", text="Antwort A", order=1),
                    QuizAnswerOption(option_id="a2", text="Antwort B", order=2),
                ],
                correct_answer=QuizCorrectAnswerReference(option_id=correct_answer),
                explanation="Richtig erklärt.",
                metadata={"progress_theme_key": "alltag"},
            )
        ],
        requested_count=1,
        returned_count=1,
        has_more=False,
    )


@pytest.mark.asyncio
async def test_submit_answer_records_wrong_answer_to_mistake_service() -> None:
    mistakes = FakeMistakeService(active_items=[])
    service = TrainingSessionService(
        user_repo=FakeUserRepository(),
        session_repo=FakeSessionRepository(),
        answer_repo=FakeAnswerRepository(),
        analytics_repo=FakeAnalyticsRepository(),
        question_reference_repo=FakeQuestionReferenceRepository(),
        session_item_repo=FakeSessionItemRepository(),
        quiz_service=FakeQuizBankService([_question_payload(item_id="q_regular", level="A1", theme="Alltag")]),
        mistakes_service=mistakes,
    )
    db = FakeDatabaseSession()
    user_id = 111

    await service.start_session(db, user_id, level="A1", theme="Alltag", total_questions=2, force_new=False)
    question = await service.get_or_create_current_question(db, user_id, force_refresh=True)

    result = await service.submit_answer(
        db,
        telegram_user_id=user_id,
        session_id=question.session_id,
        question_token=question.question_token,
        selected_option_id="a1",
    )

    assert result.is_correct is False
    assert len(mistakes.wrong_calls) == 1
    assert mistakes.wrong_calls[0]["external_quiz_id"] == "q_regular"


@pytest.mark.asyncio
async def test_submit_answer_does_not_repeat_wrong_mistake_on_duplicate_click() -> None:
    db = FakeDatabaseSession()
    user_id = 112
    mistakes = FakeMistakeService(active_items=[])
    service = TrainingSessionService(
        user_repo=FakeUserRepository(),
        session_repo=FakeSessionRepository(),
        answer_repo=FakeAnswerRepository(),
        analytics_repo=FakeAnalyticsRepository(),
        question_reference_repo=FakeQuestionReferenceRepository(),
        session_item_repo=FakeSessionItemRepository(),
        quiz_service=FakeQuizBankService([_question_payload(item_id="q_dup", level="A1", theme="Alltag")]),
        mistakes_service=mistakes,
    )

    await service.start_session(db, user_id, level="A1", theme="Alltag", total_questions=2, force_new=False)
    question = await service.get_or_create_current_question(db, user_id, force_refresh=True)

    first = await service.submit_answer(
        db,
        telegram_user_id=user_id,
        session_id=question.session_id,
        question_token=question.question_token,
        selected_option_id="a1",
    )
    second = await service.submit_answer(
        db,
        telegram_user_id=user_id,
        session_id=question.session_id,
        question_token=question.question_token,
        selected_option_id="a1",
    )

    assert first.is_duplicate is False
    assert second.is_duplicate is True
    assert len(mistakes.wrong_calls) == 1


@pytest.mark.asyncio
async def test_submit_answer_records_review_success_for_review_session() -> None:
    review_item = FakeMistake(id=1, level="A1", theme="Alltag", external_quiz_id="q_review")
    mistakes = FakeMistakeService(active_items=[review_item])
    service = TrainingSessionService(
        user_repo=FakeUserRepository(),
        session_repo=FakeSessionRepository(),
        answer_repo=FakeAnswerRepository(),
        analytics_repo=FakeAnalyticsRepository(),
        question_reference_repo=FakeQuestionReferenceRepository(),
        session_item_repo=FakeSessionItemRepository(),
        quiz_service=FakeQuizBankService([_question_payload(item_id="q_review", level="A1", theme="Alltag", correct_answer="a2")]),
        mistakes_service=mistakes,
    )
    db = FakeDatabaseSession()
    user_id = 113

    await service.start_review_session(db, user_id, force_new=False, total_questions=1)
    question = await service.get_or_create_current_question(db, user_id, force_refresh=True)

    result = await service.submit_answer(
        db,
        telegram_user_id=user_id,
        session_id=question.session_id,
        question_token=question.question_token,
        selected_option_id="a2",
    )

    assert result.is_correct is True
    assert len(mistakes.success_calls) == 1
    assert mistakes.success_calls[0]["external_quiz_id"] == "q_review"


@pytest.mark.asyncio
async def test_review_empty_quiz_bank_marks_review_items_unavailable() -> None:
    review_item = FakeMistake(id=1, level="A1", theme="Alltag", external_quiz_id="q_missing")
    mistakes = FakeMistakeService(active_items=[review_item])
    empty_response = QuizQuestionsResponse(
        items=[],
        requested_count=1,
        returned_count=0,
        has_more=False,
    )
    service = TrainingSessionService(
        user_repo=FakeUserRepository(),
        session_repo=FakeSessionRepository(),
        answer_repo=FakeAnswerRepository(),
        analytics_repo=FakeAnalyticsRepository(),
        question_reference_repo=FakeQuestionReferenceRepository(),
        session_item_repo=FakeSessionItemRepository(),
        quiz_service=FakeQuizBankService([empty_response]),
        mistakes_service=mistakes,
    )
    db = FakeDatabaseSession()
    user_id = 114

    await service.start_review_session(db, user_id, force_new=False, total_questions=1)
    with pytest.raises(NoMoreQuestionsError):
        await service.get_or_create_current_question(db, user_id, force_refresh=True)

    assert mistakes.unavailable_calls == [
        {
            "external_quiz_ids": ["q_missing"],
            "session_id": 1,
        },
    ]
    assert mistakes.active_items == []
