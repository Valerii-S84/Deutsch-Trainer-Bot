from __future__ import annotations

import asyncio
import os
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.models import QuizSession, User, UserAnswer


def _test_database_url() -> str:
    database_url = os.environ.get("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("TEST_DATABASE_URL is required for answer idempotency runtime test")
    return database_url


@pytest_asyncio.fixture
async def session_factory():
    engine = create_async_engine(_test_database_url())
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    try:
        yield factory
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_concurrent_duplicate_answer_creates_exactly_one_row(session_factory) -> None:
    marker = uuid4().hex
    telegram_user_id = int(f"77{marker[:8]}", 16)
    external_quiz_id = f"runtime-dup-{marker}"
    user_id, session_id = await _seed_session(session_factory, telegram_user_id)

    try:
        results = await asyncio.gather(
            _insert_answer(session_factory, user_id, session_id, external_quiz_id, telegram_update_id=900001),
            _insert_answer(session_factory, user_id, session_id, external_quiz_id, telegram_update_id=900002),
        )
        async with session_factory() as db:
            count = await db.scalar(
                select(func.count())
                .select_from(UserAnswer)
                .where(
                    UserAnswer.user_id == user_id,
                    UserAnswer.session_id == session_id,
                    UserAnswer.external_quiz_id == external_quiz_id,
                ),
            )
    finally:
        await _cleanup(session_factory, user_id)

    assert sorted(results) == ["accepted", "duplicate"]
    assert count == 1


async def _seed_session(session_factory, telegram_user_id: int) -> tuple[int, int]:
    async with session_factory() as db:
        user = User(telegram_user_id=telegram_user_id)
        db.add(user)
        await db.flush()
        session = QuizSession(
            user_id=user.id,
            level="A1",
            theme="Alltag",
            status="active",
            total_questions=5,
            source="local_quiz_catalog",
        )
        db.add(session)
        await db.commit()
        return user.id, session.id


async def _insert_answer(
    session_factory,
    user_id: int,
    session_id: int,
    external_quiz_id: str,
    *,
    telegram_update_id: int,
) -> str:
    async with session_factory() as db:
        answer = UserAnswer(
            user_id=user_id,
            session_id=session_id,
            external_quiz_id=external_quiz_id,
            item_id=external_quiz_id,
            level="A1",
            theme="Alltag",
            selected_answer="a1",
            correct_answer="a2",
            is_correct=False,
            session_type="regular",
            telegram_update_id=telegram_update_id,
        )
        db.add(answer)
        try:
            await db.commit()
        except IntegrityError:
            await db.rollback()
            return "duplicate"
        return "accepted"


async def _cleanup(session_factory, user_id: int) -> None:
    async with session_factory() as db:
        await db.execute(delete(User).where(User.id == user_id))
        await db.commit()
