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
    resolved_at: datetime | None = None
    status: MistakeStatus = MistakeStatus.new
    last_seen_at: datetime | None = None
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
        mistake.wrong_answer = wrong_answer
        mistake.correct_answer = correct_answer
        mistake.status = MistakeStatus.repeated
        mistake.last_seen_at = datetime.now(UTC)
        if source_snapshot is not None:
            mistake.source_snapshot = source_snapshot
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
        mistake.wrong_answer = wrong_answer
        mistake.correct_answer = correct_answer
        mistake.resolved_at = None
        mistake.status = MistakeStatus.repeated
        mistake.last_seen_at = datetime.now(UTC)
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

    async def list_active_for_user(self, db, *, user_id: int) -> list[FakeMistake]:
        self.calls["list"] += 1
        return [m for m in self._mistakes.values() if m.user_id == user_id and m.resolved_at is None]

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


@pytest.mark.asyncio
async def test_record_wrong_answer_creates_new_mistake_on_first_wrong() -> None:
    service = MistakeService(
        user_repo=FakeUserRepository(),
        mistake_repo=FakeMistakeRepository(),
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


@pytest.mark.asyncio
async def test_record_wrong_answer_increments_count_for_active_repeat() -> None:
    user_repo = FakeUserRepository()
    repo = FakeMistakeRepository()
    service = MistakeService(user_repo=user_repo, mistake_repo=repo)
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
    service = MistakeService(user_repo=user_repo, mistake_repo=repo)
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
    service = MistakeService(user_repo=user_repo, mistake_repo=repo)
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
    resolved = await service.record_review_success(
        db,
        telegram_user_id=123,
        external_quiz_id="q4",
        question_level="A1",
        question_theme="Alltag",
        correct_answer="a1",
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


@pytest.mark.asyncio
async def test_get_weak_areas_uses_repository_summary() -> None:
    user_repo = FakeUserRepository()
    repo = FakeMistakeRepository()
    service = MistakeService(user_repo=user_repo, mistake_repo=repo)
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
