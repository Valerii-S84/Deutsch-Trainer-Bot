from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

import pytest

from app.quiz_bank import QuizBankRequestContext
from app.quiz_bank.schemas import QuizAnswerOption, QuizCorrectAnswerReference, QuizItem, QuizQuestionsResponse
from app.services.entitlements import DailyLimitExceededError
from app.services.training_session import (
    ActiveSessionConflictError,
    ActiveSessionNotFoundError,
    NoMoreQuestionsError,
    QuestionStateError,
    TrainingSessionService,
)
from app.repositories.quiz_sessions import QuizSessionStatus


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
    finished_at: str | None = None


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
        self.create_calls = 0
        self._next_id = 1

    async def get_by_telegram_id(self, db, telegram_user_id: int) -> FakeUser | None:
        return self._users.get(telegram_user_id)

    async def create_if_missing(self, db, telegram_user_id: int) -> FakeUser:
        user = self._users.get(telegram_user_id)
        if user is None:
            self.create_calls += 1
            user = FakeUser(id=self._next_id, telegram_user_id=telegram_user_id)
            self._next_id += 1
            self._users[telegram_user_id] = user
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
            correct_answers=0,
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
        session.correct_answers = session.correct_answers + delta
        return session.correct_answers

    async def increment_shown_questions_count(self, db, session: FakeSession, delta: int) -> int:
        session.shown_questions_count += delta
        return session.shown_questions_count


class FakeAnswerRepository:
    def __init__(self) -> None:
        self._answers: list[FakeAnswer] = []
        self.create_calls = 0
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
        self.create_calls += 1
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


class StubQuizBankService:
    def __init__(self, responses: list[object]) -> None:
        self._responses = list(responses)
        self.calls: list[tuple[str, str | None, int, dict | None]] = []

    async def request_quiz(
        self,
        *,
        level: str,
        theme: str | None,
        limit: int,
        user_context: QuizBankRequestContext | None = None,
    ):
        self.calls.append((level, theme, limit, user_context.model_dump(exclude_none=True) if user_context else None))
        return self._responses.pop(0)


class FakeEntitlementService:
    def __init__(self, *, limit_exceeded: bool = False) -> None:
        self.limit_exceeded = limit_exceeded
        self.ensure_calls: list[dict[str, object]] = []
        self.charge_calls = 0

    async def ensure_daily_question_available(self, db, telegram_user_id: int, **kwargs: object):
        self.ensure_calls.append({"telegram_user_id": telegram_user_id, **kwargs})
        if self.limit_exceeded:
            state = SimpleNamespace(
                plan="free",
                question_limit=1,
                questions_used=1,
                remaining=0,
                reset_at=None,
                daily_limit=SimpleNamespace(id=77, user_id=telegram_user_id),
            )
            raise DailyLimitExceededError(state)
        return SimpleNamespace(remaining=1)

    async def charge_daily_question(self, db, telegram_user_id: int, **kwargs: object):
        self.charge_calls += 1
        return SimpleNamespace(daily_limit=SimpleNamespace(id=77))

    async def ensure_entitlement(self, db, telegram_user_id: int, **kwargs: object):
        return SimpleNamespace(allowed=True)


def _question_payload(item_id: str = "q1", correct_answer: str = "a2") -> QuizQuestionsResponse:
    return QuizQuestionsResponse(
        items=[
            QuizItem(
                item_id=item_id,
                level="A1",
                theme="Alltag",
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


def _make_service(quiz_responses: list[object]) -> TrainingSessionService:
    return TrainingSessionService(
        user_repo=FakeUserRepository(),
        session_repo=FakeSessionRepository(),
        answer_repo=FakeAnswerRepository(),
        analytics_repo=FakeAnalyticsRepository(),
        question_reference_repo=FakeQuestionReferenceRepository(),
        session_item_repo=FakeSessionItemRepository(),
        quiz_service=StubQuizBankService(quiz_responses),
    )


@pytest.mark.asyncio
async def test_user_bootstrap_created_once_for_same_telegram_id() -> None:
    user_repo = FakeUserRepository()
    session_repo = FakeSessionRepository()
    answer_repo = FakeAnswerRepository()
    service = TrainingSessionService(
        user_repo=user_repo,
        session_repo=session_repo,
        answer_repo=answer_repo,
        analytics_repo=FakeAnalyticsRepository(),
        question_reference_repo=FakeQuestionReferenceRepository(),
        session_item_repo=FakeSessionItemRepository(),
        quiz_service=StubQuizBankService([]),
    )
    db = FakeDatabaseSession()

    await service.start_session(db, telegram_user_id=111, level="A1", theme="Alltag", total_questions=5, force_new=False)
    await service.start_session(db, telegram_user_id=111, level="A1", theme="Alltag", total_questions=5, force_new=True)

    user = await service.get_user(db, 111)
    assert user_repo.create_calls == 1
    assert user.id == 1


@pytest.mark.asyncio
async def test_start_session_rejects_existing_active_session_when_not_forced() -> None:
    service = _make_service([])
    db = FakeDatabaseSession()

    await service.start_session(db, telegram_user_id=123, level="A1", theme="Alltag", total_questions=4, force_new=False)
    with pytest.raises(ActiveSessionConflictError):
        await service.start_session(db, telegram_user_id=123, level="A1", theme="Alltag", total_questions=4, force_new=False)


@pytest.mark.asyncio
async def test_submit_answer_marks_score_once_for_duplicate_click() -> None:
    service = _make_service([_question_payload()])
    service._session_repo  # type: ignore[attr-defined]
    db = FakeDatabaseSession()
    user_id = 321

    await service.start_session(db, telegram_user_id=user_id, level="A1", theme="Alltag", total_questions=2, force_new=False)
    question = await service.get_or_create_current_question(db, telegram_user_id=user_id, force_refresh=True)

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

    assert first.is_correct is False
    assert first.is_duplicate is False
    assert second.is_duplicate is True
    assert first.correct_answers == 0
    assert second.correct_answers == 0

    user = await service.get_user(db, user_id)
    active_session = await service._session_repo.get_active_for_user(db, user.id)  # type: ignore[attr-defined]
    assert active_session is not None
    assert active_session.correct_answers == 0


@pytest.mark.asyncio
async def test_current_question_creates_shown_item_lifecycle() -> None:
    service = _make_service([_question_payload(item_id="q_lifecycle")])
    db = FakeDatabaseSession()
    user_id = 322

    await service.start_session(db, telegram_user_id=user_id, level="A1", theme="Alltag", total_questions=2, force_new=False)
    question = await service.get_or_create_current_question(db, telegram_user_id=user_id, force_refresh=True)

    user = await service.get_user(db, user_id)
    active_session = await service._session_repo.get_active_for_user(db, user.id)  # type: ignore[attr-defined]
    session_item = await service._session_item_repo.get_by_session_item(  # type: ignore[attr-defined]
        db,
        session_id=question.session_id,
        item_id="q_lifecycle",
    )

    assert question.training_session_item_id is not None
    assert question.question_reference_id is not None
    assert question.metadata_snapshot == {"progress_theme_key": "alltag"}
    assert active_session is not None
    assert active_session.shown_questions_count == 1
    assert session_item is not None
    assert session_item.status == "shown"
    assert session_item.daily_limit_charged_at == "now"


@pytest.mark.asyncio
async def test_get_next_question_rejects_stale_token_before_fetching() -> None:
    service = _make_service([_question_payload(item_id="q1"), _question_payload(item_id="q2")])
    db = FakeDatabaseSession()
    user_id = 323

    await service.start_session(db, telegram_user_id=user_id, level="A1", theme="Alltag", total_questions=2, force_new=False)
    question = await service.get_or_create_current_question(db, telegram_user_id=user_id, force_refresh=True)

    with pytest.raises(QuestionStateError):
        await service.get_next_question(
            db,
            telegram_user_id=user_id,
            session_id=question.session_id,
            answered_question_token="stale",
        )

    assert len(service._quiz_service.calls) == 1  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_submit_answer_rejects_unknown_option_without_answer_row() -> None:
    service = _make_service([_question_payload()])
    db = FakeDatabaseSession()
    user_id = 324

    await service.start_session(db, telegram_user_id=user_id, level="A1", theme="Alltag", total_questions=2, force_new=False)
    question = await service.get_or_create_current_question(db, telegram_user_id=user_id, force_refresh=True)

    with pytest.raises(QuestionStateError):
        await service.submit_answer(
            db,
            telegram_user_id=user_id,
            session_id=question.session_id,
            question_token=question.question_token,
            selected_option_id="unknown",
        )

    assert service._answer_repo.create_calls == 0  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_submit_answer_from_another_user_is_rejected() -> None:
    service = _make_service([_question_payload()])
    db = FakeDatabaseSession()

    await service.start_session(db, telegram_user_id=401, level="A1", theme="Alltag", total_questions=2, force_new=False)
    question = await service.get_or_create_current_question(db, telegram_user_id=401, force_refresh=True)

    with pytest.raises(ActiveSessionNotFoundError):
        await service.submit_answer(
            db,
            telegram_user_id=402,
            session_id=question.session_id,
            question_token=question.question_token,
            selected_option_id="a2",
        )

    assert service._answer_repo.create_calls == 0  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_submit_answer_completes_session_and_clears_pending() -> None:
    service = _make_service([_question_payload(correct_answer="a2")])
    db = FakeDatabaseSession()
    user_id = 222

    await service.start_session(db, telegram_user_id=user_id, level="A1", theme="Alltag", total_questions=1, force_new=False)
    question = await service.get_or_create_current_question(db, telegram_user_id=user_id, force_refresh=True)

    result = await service.submit_answer(
        db,
        telegram_user_id=user_id,
        session_id=question.session_id,
        question_token=question.question_token,
        selected_option_id="a2",
    )

    user = await service.get_user(db, user_id)
    completed_session = await service._session_repo.get_by_id_for_user(db, question.session_id, user.id)  # type: ignore[attr-defined]
    session_item = await service._session_item_repo.get_by_session_item(  # type: ignore[attr-defined]
        db,
        session_id=question.session_id,
        item_id=question.question_id,
    )
    assert result.is_completed is True
    assert result.correct_answers == 1
    assert completed_session is not None
    assert completed_session.status == QuizSessionStatus.completed
    assert completed_session.api_metadata.get("pending_question") is None
    assert session_item is not None
    assert session_item.status == "answered"
    event_names = [event.event_name for event in service._analytics_repo.events]  # type: ignore[attr-defined]
    assert event_names == ["training_started", "question_answered", "training_completed", "result_shown"]


@pytest.mark.asyncio
async def test_completed_session_does_not_accept_new_answer() -> None:
    service = _make_service([_question_payload(correct_answer="a2")])
    db = FakeDatabaseSession()
    user_id = 223

    await service.start_session(db, telegram_user_id=user_id, level="A1", theme="Alltag", total_questions=1, force_new=False)
    question = await service.get_or_create_current_question(db, telegram_user_id=user_id, force_refresh=True)
    await service.submit_answer(
        db,
        telegram_user_id=user_id,
        session_id=question.session_id,
        question_token=question.question_token,
        selected_option_id="a2",
    )

    with pytest.raises(ActiveSessionNotFoundError):
        await service.submit_answer(
            db,
            telegram_user_id=user_id,
            session_id=question.session_id,
            question_token=question.question_token,
            selected_option_id="a2",
        )


@pytest.mark.asyncio
async def test_get_question_marks_session_failed_when_quiz_bank_empty() -> None:
    empty_batch = QuizQuestionsResponse(
        items=[],
        requested_count=1,
        returned_count=0,
        has_more=False,
    )
    service = _make_service([empty_batch])
    db = FakeDatabaseSession()
    user_id = 333

    await service.start_session(db, telegram_user_id=user_id, level="A1", theme="Alltag", total_questions=1, force_new=False)
    with pytest.raises(NoMoreQuestionsError):
        await service.get_or_create_current_question(db, telegram_user_id=user_id, force_refresh=True)

    user = await service.get_user(db, user_id)
    active = await service._session_repo.get_active_for_user(db, user.id)  # type: ignore[attr-defined]
    assert active is None


@pytest.mark.asyncio
async def test_get_question_charges_daily_limit_when_question_is_shown() -> None:
    entitlement_service = FakeEntitlementService()
    service = TrainingSessionService(
        user_repo=FakeUserRepository(),
        session_repo=FakeSessionRepository(),
        answer_repo=FakeAnswerRepository(),
        analytics_repo=FakeAnalyticsRepository(),
        question_reference_repo=FakeQuestionReferenceRepository(),
        session_item_repo=FakeSessionItemRepository(),
        quiz_service=StubQuizBankService([_question_payload(item_id="q_limit")]),
        entitlement_service=entitlement_service,
    )
    db = FakeDatabaseSession()
    user_id = 334

    await service.start_session(
        db,
        telegram_user_id=user_id,
        level="A1",
        theme="Alltag",
        total_questions=1,
        force_new=False,
    )
    question = await service.get_or_create_current_question(db, telegram_user_id=user_id, force_refresh=True)
    session_item = await service._session_item_repo.get_by_session_item(  # type: ignore[attr-defined]
        db,
        session_id=question.session_id,
        item_id="q_limit",
    )

    assert entitlement_service.charge_calls == 1
    assert session_item is not None
    assert session_item.daily_limit_charged_at == "now"
    assert session_item.daily_limit_id == 77


@pytest.mark.asyncio
async def test_daily_limit_hit_blocks_quiz_request_before_api_call() -> None:
    entitlement_service = FakeEntitlementService(limit_exceeded=True)
    quiz_service = StubQuizBankService([_question_payload(item_id="q_never")])
    service = TrainingSessionService(
        user_repo=FakeUserRepository(),
        session_repo=FakeSessionRepository(),
        answer_repo=FakeAnswerRepository(),
        analytics_repo=FakeAnalyticsRepository(),
        question_reference_repo=FakeQuestionReferenceRepository(),
        session_item_repo=FakeSessionItemRepository(),
        quiz_service=quiz_service,
        entitlement_service=entitlement_service,
    )
    db = FakeDatabaseSession()

    with pytest.raises(DailyLimitExceededError):
        await service.start_session(
            db,
            telegram_user_id=335,
            level="A1",
            theme="Alltag",
            total_questions=1,
            force_new=False,
        )

    assert quiz_service.calls == []


def _force_new_replaces_active_session(service: TrainingSessionService, db: FakeDatabaseSession, user_id: int) -> None:
    import asyncio
    loop = asyncio.get_running_loop()
    previous = loop.run_until_complete(service.start_session(db, telegram_user_id=user_id, level="A1", theme="Alltag", total_questions=1, force_new=False))
    _ = previous


@pytest.mark.asyncio
async def test_force_new_session_replaces_existing_active() -> None:
    service = _make_service([])
    db = FakeDatabaseSession()
    user_id = 444

    first = await service.start_session(db, telegram_user_id=user_id, level="A1", theme="Alltag", total_questions=3, force_new=False)
    second = await service.start_session(db, telegram_user_id=user_id, level="A1", theme="Beruf", total_questions=3, force_new=True)

    user = await service.get_user(db, user_id)
    active = await service._session_repo.get_active_for_user(db, user.id)  # type: ignore[attr-defined]
    assert active is not None
    assert active.id == second.id
    assert first.status == QuizSessionStatus.cancelled
    assert active.theme == "Beruf"
