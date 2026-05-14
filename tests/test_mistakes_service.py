from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

import pytest

from app.db.models.mistake import MistakeStatus
from app.services.mistakes import MistakeService


@dataclass
class FakeUser:
    id: int
    telegram_user_id: int


@dataclass
class FakeMistake:
    id: int
    user_id: int
    external_quiz_id: str
    level: str
    theme: str
    wrong_answer: str
    correct_answer: str
    mistake_count: int = 1
    successful_repeats_count: int = 0
    successful_repeat_days_count: int = 0
    resolved_at: datetime | None = None
    status: MistakeStatus = MistakeStatus.new
    last_seen_at: datetime | None = None
    last_mistake_at: datetime | None = None
    last_successful_repeat_at: datetime | None = None
    content_available: bool = True
    source_snapshot: dict | None = None


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


class FakeMistakeRepository:
    def __init__(self) -> None:
        self.calls: dict[str, int] = {
            "create": 0,
            "increment": 0,
            "reopen": 0,
            "resolve": 0,
            "successful_repeat": 0,
            "content_unavailable": 0,
            "list": 0,
        }
        self._mistakes: dict[str, FakeMistake] = {}
        self._next_id = 1

    async def find_active_by_user_and_external_quiz_id(
        self,
        db,
        *,
        user_id: int,
        external_quiz_id: str,
    ) -> FakeMistake | None:
        item = self._mistakes.get(external_quiz_id)
        if item is None or item.user_id != user_id or item.resolved_at is not None:
            return None
        return item

    async def get_active_by_user_and_external_quiz_id(
        self,
        db,
        *,
        user_id: int,
        external_quiz_id: str,
    ) -> FakeMistake | None:
        return await self.find_active_by_user_and_external_quiz_id(
            db,
            user_id=user_id,
            external_quiz_id=external_quiz_id,
        )

    async def get_by_user_and_external_quiz_id(
        self,
        db,
        *,
        user_id: int,
        external_quiz_id: str,
        active_only: bool = False,
    ) -> FakeMistake | None:
        item = self._mistakes.get(external_quiz_id)
        if item is None or item.user_id != user_id:
            return None
        if active_only and item.resolved_at is not None:
            return None
        return item

    async def create(
        self,
        db,
        *,
        user_id: int,
        external_quiz_id: str,
        level: str,
        theme: str,
        wrong_answer: str,
        correct_answer: str,
        source_snapshot: dict | None = None,
    ) -> FakeMistake:
        self.calls["create"] += 1
        mistake = FakeMistake(
            id=self._next_id,
            user_id=user_id,
            external_quiz_id=external_quiz_id,
            level=level,
            theme=theme,
            wrong_answer=wrong_answer,
            correct_answer=correct_answer,
            source_snapshot=source_snapshot,
            last_seen_at=datetime.now(UTC),
            last_mistake_at=datetime.now(UTC),
        )
        self._next_id += 1
        self._mistakes[external_quiz_id] = mistake
        return mistake

    async def increment_wrong(
        self,
        db,
        mistake: FakeMistake,
        *,
        wrong_answer: str,
        correct_answer: str,
        source_snapshot: dict | None = None,
    ) -> FakeMistake:
        self.calls["increment"] += 1
        mistake.mistake_count += 1
        mistake.successful_repeats_count = 0
        mistake.successful_repeat_days_count = 0
        mistake.last_successful_repeat_at = None
        mistake.wrong_answer = wrong_answer
        mistake.correct_answer = correct_answer
        mistake.status = MistakeStatus.repeated
        mistake.resolved_at = None
        mistake.content_available = True
        mistake.last_seen_at = datetime.now(UTC)
        mistake.last_mistake_at = mistake.last_seen_at
        if source_snapshot is not None:
            mistake.source_snapshot = source_snapshot
        return mistake

    async def record_successful_repeat(
        self,
        db,
        mistake: FakeMistake,
        *,
        correct_answer: str,
        answered_at: datetime | None = None,
    ) -> FakeMistake:
        self.calls["successful_repeat"] += 1
        now = answered_at or datetime.now(UTC)
        mistake.successful_repeats_count += 1
        if mistake.last_successful_repeat_at is None or (
            mistake.last_successful_repeat_at.date() != now.date()
        ):
            mistake.successful_repeat_days_count += 1
        mistake.correct_answer = correct_answer
        mistake.last_successful_repeat_at = now
        mistake.last_seen_at = now
        mistake.content_available = True
        if mistake.successful_repeats_count >= 3 and mistake.successful_repeat_days_count >= 2:
            mistake.status = MistakeStatus.resolved
            mistake.resolved_at = now
            return mistake
        mistake.status = MistakeStatus.improved
        mistake.resolved_at = None
        return mistake

    async def reopen_as_active(
        self,
        db,
        mistake: FakeMistake,
        *,
        wrong_answer: str,
        correct_answer: str,
        source_snapshot: dict | None = None,
    ) -> FakeMistake:
        self.calls["reopen"] += 1
        mistake.mistake_count += 1
        mistake.successful_repeats_count = 0
        mistake.successful_repeat_days_count = 0
        mistake.last_successful_repeat_at = None
        mistake.wrong_answer = wrong_answer
        mistake.correct_answer = correct_answer
        mistake.resolved_at = None
        mistake.status = MistakeStatus.repeated
        mistake.content_available = True
        mistake.last_seen_at = datetime.now(UTC)
        mistake.last_mistake_at = mistake.last_seen_at
        if source_snapshot is not None:
            mistake.source_snapshot = source_snapshot
        return mistake

    async def resolve(
        self,
        db,
        mistake: FakeMistake,
    ) -> FakeMistake:
        self.calls["resolve"] += 1
        mistake.status = MistakeStatus.resolved
        mistake.resolved_at = datetime.now(UTC)
        return mistake

    async def mark_content_unavailable(self, db, mistake: FakeMistake) -> FakeMistake:
        self.calls["content_unavailable"] += 1
        mistake.content_available = False
        mistake.last_seen_at = datetime.now(UTC)
        return mistake

    async def list_active_for_user(self, db, *, user_id: int) -> list[FakeMistake]:
        self.calls["list"] += 1
        return [
            m
            for m in self._mistakes.values()
            if m.user_id == user_id and m.resolved_at is None and m.content_available
        ]

    async def get_weak_area_summary(self, db, *, user_id: int) -> list[dict[str, object]]:
        self.calls["list"] += 1
        summary: dict[tuple[str, str], int] = {}
        for item in self._mistakes.values():
            if item.user_id != user_id or item.resolved_at is not None:
                continue
            key = (item.level, item.theme)
            summary[key] = summary.get(key, 0) + item.mistake_count
        return [
            {"level": level, "theme": theme, "mistake_count": count}
            for (level, theme), count in sorted(summary.items())
        ]


class FakeDb:
    pass


class FakeMistakeHistoryRepository:
    def __init__(self) -> None:
        self.records: list[dict[str, object]] = []

    async def record(self, db, *, mistake: FakeMistake, event_type: str, **kwargs: object) -> None:
        self.records.append({"mistake_id": mistake.id, "event_type": event_type, **kwargs})


def _mistake_service(user_repo: FakeUserRepository, repo: FakeMistakeRepository) -> MistakeService:
    return MistakeService(
        user_repo=user_repo,
        mistake_repo=repo,
        mistake_history_repo=FakeMistakeHistoryRepository(),
    )


@pytest.mark.asyncio
async def test_record_wrong_answer_creates_new_mistake_on_first_wrong() -> None:
    history_repo = FakeMistakeHistoryRepository()
    service = MistakeService(
        user_repo=FakeUserRepository(),
        mistake_repo=FakeMistakeRepository(),
        mistake_history_repo=history_repo,
    )
    db = FakeDb()

    mistake = await service.record_wrong_answer(
        db,
        telegram_user_id=123,
        external_quiz_id="q1",
        level="A1",
        theme="Alltag",
        wrong_answer="a2",
        correct_answer="a1",
    )

    assert mistake is not None
    assert mistake.external_quiz_id == "q1"
    assert mistake.mistake_count == 1
    assert len(history_repo.records) == 1
    assert history_repo.records[0]["event_type"] == "wrong_created"


@pytest.mark.asyncio
async def test_record_wrong_answer_increments_count_for_active_repeat() -> None:
    user_repo = FakeUserRepository()
    repo = FakeMistakeRepository()
    service = _mistake_service(user_repo, repo)
    db = FakeDb()

    await service.record_wrong_answer(
        db,
        telegram_user_id=123,
        external_quiz_id="q2",
        level="A1",
        theme="Alltag",
        wrong_answer="a2",
        correct_answer="a1",
    )
    duplicate = await service.record_wrong_answer(
        db,
        telegram_user_id=123,
        external_quiz_id="q2",
        level="A1",
        theme="Alltag",
        wrong_answer="a3",
        correct_answer="a1",
    )

    assert repo.calls["create"] == 1
    assert repo.calls["increment"] == 1
    assert duplicate is not None
    assert duplicate.mistake_count == 2


@pytest.mark.asyncio
async def test_record_wrong_answer_is_duplicate_does_not_change_state() -> None:
    user_repo = FakeUserRepository()
    repo = FakeMistakeRepository()
    service = _mistake_service(user_repo, repo)
    db = FakeDb()

    first = await service.record_wrong_answer(
        db,
        telegram_user_id=123,
        external_quiz_id="q3",
        level="A1",
        theme="Alltag",
        wrong_answer="a2",
        correct_answer="a1",
    )
    duplicate = await service.record_wrong_answer(
        db,
        telegram_user_id=123,
        external_quiz_id="q3",
        level="A1",
        theme="Alltag",
        wrong_answer="a4",
        correct_answer="a1",
        is_duplicate=True,
    )

    assert first is not None
    assert duplicate is not None
    assert duplicate.mistake_count == 1
    assert repo.calls["increment"] == 0
    assert repo.calls["create"] == 1


@pytest.mark.asyncio
async def test_record_wrong_answer_reopens_resolved_mistake() -> None:
    user_repo = FakeUserRepository()
    repo = FakeMistakeRepository()
    service = _mistake_service(user_repo, repo)
    db = FakeDb()

    first = await service.record_wrong_answer(
        db,
        telegram_user_id=123,
        external_quiz_id="q4",
        level="A1",
        theme="Alltag",
        wrong_answer="a2",
        correct_answer="a1",
    )
    assert first is not None
    await service.record_review_success(
        db,
        telegram_user_id=123,
        external_quiz_id="q4",
        question_level="A1",
        question_theme="Alltag",
        correct_answer="a1",
        answered_at=datetime(2026, 5, 14, 10, 0, tzinfo=UTC),
    )
    await service.record_review_success(
        db,
        telegram_user_id=123,
        external_quiz_id="q4",
        question_level="A1",
        question_theme="Alltag",
        correct_answer="a1",
        answered_at=datetime(2026, 5, 14, 11, 0, tzinfo=UTC),
    )
    resolved = await service.record_review_success(
        db,
        telegram_user_id=123,
        external_quiz_id="q4",
        question_level="A1",
        question_theme="Alltag",
        correct_answer="a1",
        answered_at=datetime(2026, 5, 15, 10, 0, tzinfo=UTC),
    )
    assert resolved is not None
    assert resolved.resolved_at is not None

    reopened = await service.record_wrong_answer(
        db,
        telegram_user_id=123,
        external_quiz_id="q4",
        level="A1",
        theme="Alltag",
        wrong_answer="a3",
        correct_answer="a1",
    )

    assert reopened is not None
    assert reopened.resolved_at is None
    assert reopened.mistake_count == 2
    assert reopened.status == MistakeStatus.repeated
    assert reopened.successful_repeats_count == 0


@pytest.mark.asyncio
async def test_one_correct_review_marks_improved_not_resolved() -> None:
    user_repo = FakeUserRepository()
    repo = FakeMistakeRepository()
    history_repo = FakeMistakeHistoryRepository()
    service = MistakeService(
        user_repo=user_repo,
        mistake_repo=repo,
        mistake_history_repo=history_repo,
    )
    db = FakeDb()

    await service.record_wrong_answer(
        db,
        telegram_user_id=123,
        external_quiz_id="q6",
        level="A1",
        theme="Alltag",
        wrong_answer="a2",
        correct_answer="a1",
    )
    improved = await service.record_review_success(
        db,
        telegram_user_id=123,
        external_quiz_id="q6",
        question_level="A1",
        question_theme="Alltag",
        correct_answer="a1",
        answered_at=datetime(2026, 5, 14, 10, 0, tzinfo=UTC),
    )

    assert improved is not None
    assert improved.status == MistakeStatus.improved
    assert improved.resolved_at is None
    assert improved.successful_repeats_count == 1
    assert improved.successful_repeat_days_count == 1
    assert history_repo.records[-1]["event_type"] == "review_improved"


@pytest.mark.asyncio
async def test_repeated_correct_reviews_across_days_resolve() -> None:
    user_repo = FakeUserRepository()
    repo = FakeMistakeRepository()
    history_repo = FakeMistakeHistoryRepository()
    service = MistakeService(
        user_repo=user_repo,
        mistake_repo=repo,
        mistake_history_repo=history_repo,
    )
    db = FakeDb()

    await service.record_wrong_answer(
        db,
        telegram_user_id=123,
        external_quiz_id="q7",
        level="A1",
        theme="Alltag",
        wrong_answer="a2",
        correct_answer="a1",
    )
    for answered_at in (
        datetime(2026, 5, 14, 10, 0, tzinfo=UTC),
        datetime(2026, 5, 14, 11, 0, tzinfo=UTC),
        datetime(2026, 5, 15, 10, 0, tzinfo=UTC),
    ):
        resolved = await service.record_review_success(
            db,
            telegram_user_id=123,
            external_quiz_id="q7",
            question_level="A1",
            question_theme="Alltag",
            correct_answer="a1",
            answered_at=answered_at,
        )

    assert resolved is not None
    assert resolved.status == MistakeStatus.resolved
    assert resolved.successful_repeats_count == 3
    assert resolved.successful_repeat_days_count == 2
    assert history_repo.records[-1]["event_type"] == "review_resolved"


@pytest.mark.asyncio
async def test_mark_review_items_unavailable_preserves_mistake_but_hides_review_item() -> None:
    user_repo = FakeUserRepository()
    repo = FakeMistakeRepository()
    history_repo = FakeMistakeHistoryRepository()
    service = MistakeService(
        user_repo=user_repo,
        mistake_repo=repo,
        mistake_history_repo=history_repo,
    )
    db = FakeDb()

    mistake = await service.record_wrong_answer(
        db,
        telegram_user_id=123,
        external_quiz_id="q8",
        level="A1",
        theme="Alltag",
        wrong_answer="a2",
        correct_answer="a1",
    )
    updated = await service.mark_review_items_unavailable(
        db,
        telegram_user_id=123,
        external_quiz_ids=["q8"],
        session_id=44,
    )
    review_items = await service.get_review_items(db, telegram_user_id=123)

    assert mistake is not None
    assert updated == [mistake]
    assert mistake.content_available is False
    assert mistake.resolved_at is None
    assert review_items == []
    assert history_repo.records[-1]["event_type"] == "content_unavailable"


@pytest.mark.asyncio
async def test_get_weak_areas_uses_repository_summary() -> None:
    user_repo = FakeUserRepository()
    repo = FakeMistakeRepository()
    service = _mistake_service(user_repo, repo)
    db = FakeDb()

    await service.record_wrong_answer(
        db,
        telegram_user_id=111,
        external_quiz_id="q5",
        level="A1",
        theme="Alltag",
        wrong_answer="a1",
        correct_answer="a2",
    )
    summary = await service.get_weak_areas(db, telegram_user_id=111)

    assert summary == [{"level": "A1", "theme": "Alltag", "mistake_count": 1}]
