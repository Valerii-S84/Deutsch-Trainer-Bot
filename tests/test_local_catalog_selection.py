from __future__ import annotations

import asyncio

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.catalog.selection import (
    CatalogLevelDisabledError,
    CatalogQuestionRequest,
    LocalCatalogSelector,
    selection_key_for_seed,
)
from app.db import models  # noqa: F401
from app.db.base import Base
from app.db.models import QuizCatalog, QuizCatalogItem


def test_selector_uses_selection_key_seek_without_random_sql() -> None:
    async def scenario(session: AsyncSession) -> str:
        threshold = selection_key_for_seed("user:1:session:1")
        await _seed(session, [_item("low", threshold - 10), _item("high", threshold + 10)])
        request = CatalogQuestionRequest("cat", "user:1:session:1", level="A1", theme_id="T01")
        statement = LocalCatalogSelector()._seek_query(LocalCatalogSelector()._base_query(request), threshold, wrap=False)
        question = await LocalCatalogSelector().next_question(session, request)
        assert question is not None
        assert question.item_id == "high"
        return str(statement)

    sql = asyncio.run(_with_session(scenario))

    assert "random" not in sql.lower()


def test_selector_wraps_to_lowest_key_when_threshold_is_above_all_rows() -> None:
    async def scenario(session: AsyncSession) -> str:
        threshold = selection_key_for_seed("seed")
        await _seed(session, [_item("a", threshold - 20), _item("b", threshold - 10)])
        question = await LocalCatalogSelector().next_question(
            session,
            CatalogQuestionRequest("cat", "seed", level="A1", theme_id="T01"),
        )
        assert question is not None
        return question.item_id

    assert asyncio.run(_with_session(scenario)) == "a"


def test_selector_accepts_theme_slug_from_theme_menu() -> None:
    async def scenario(session: AsyncSession) -> str:
        await _seed(session, [_item("a", 10, theme_id="T01")])
        question = await LocalCatalogSelector().next_question(
            session,
            CatalogQuestionRequest("cat", "seed", level="A1", theme_id="t01"),
        )
        assert question is not None
        return question.item_id

    assert asyncio.run(_with_session(scenario)) == "a"


def test_selector_blocks_c2_when_runtime_levels_exclude_it() -> None:
    async def scenario(session: AsyncSession) -> None:
        await _seed(session, [_item("c2", 10, level="C2")])
        with pytest.raises(CatalogLevelDisabledError):
            await LocalCatalogSelector().next_question(session, CatalogQuestionRequest("cat", "seed", level="C2"))

    asyncio.run(_with_session(scenario))


def test_selector_lists_active_themes_for_enabled_level() -> None:
    async def scenario(session: AsyncSession) -> list[tuple[str, int]]:
        await _seed(session, [_item("a", 10), _item("b", 20, status="draft"), _item("c", 30, theme_id="T02")])
        themes = await LocalCatalogSelector().list_themes(session, catalog_id="cat", level="A1")
        return [(theme.theme_id, theme.item_count) for theme in themes]

    assert asyncio.run(_with_session(scenario)) == [("T01", 1), ("T02", 1)]


async def _with_session(callback):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        async with session.begin():
            result = await callback(session)
    await engine.dispose()
    return result


async def _seed(session: AsyncSession, items: list[QuizCatalogItem]) -> None:
    session.add(QuizCatalog(catalog_id="cat", catalog_version="v1", source="test", checksum="catalog"))
    for item in items:
        session.add(item)


def _item(
    item_id: str,
    selection_key: int,
    *,
    level: str = "A1",
    theme_id: str = "T01",
    status: str = "reviewed",
) -> QuizCatalogItem:
    return QuizCatalogItem(
        catalog_id="cat",
        item_id=item_id,
        item_version="1.0",
        language="de",
        level=level,
        sublevel=level,
        theme_id=theme_id,
        theme_slug=theme_id.lower(),
        stem_text=f"Question {item_id}",
        options=["a", "b"],
        answer_key="0",
        status=status,
        source="test",
        checksum=f"checksum-{item_id}",
        selection_key=selection_key,
        is_active=status == "reviewed",
    )
