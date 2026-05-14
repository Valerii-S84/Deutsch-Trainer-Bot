from __future__ import annotations

from dataclasses import dataclass

import pytest

from app.quiz_bank import QuizBankRequestContext
from app.quiz_bank.schemas import QuizAnswerOption, QuizCorrectAnswerReference, QuizItem, QuizQuestionsResponse
from app.services.training_session import ActiveSessionConflictError, NoMoreQuestionsError, TrainingSessionService
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
    source_metadata: dict | None = None
    api_metadata: dict | None = None
    finished_at: str | None = None


@dataclass
class FakeAnswer:
    session_id: int
    user_id: int
    external_quiz_id: str
    selected_answer: str
    correct_answer: str
    is_correct: bool


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


class FakeAnswerRepository:
    def __init__(self) -> None:
        self._answers: list[FakeAnswer] = []
        self.create_calls = 0

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
        quiz_source: str | None = None,
        external_ref: str | None = None,
    ) -> FakeAnswer:
        answer = FakeAnswer(
            session_id=session_id,
            user_id=user_id,
            external_quiz_id=external_quiz_id,
            selected_answer=selected_answer,
            correct_answer=correct_answer,
            is_correct=is_correct,
        )
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
    assert result.is_completed is True
    assert result.correct_answers == 1
    assert completed_session is not None
    assert completed_session.status == QuizSessionStatus.completed
    assert completed_session.api_metadata.get("pending_question") is None


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
