from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from typing import TypeVar

from pydantic import BaseModel, ValidationError
from redis.exceptions import RedisError
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.catalog.selection import CatalogQuestionRequest, LocalCatalogQuestion, LocalCatalogSelector
from app.config import Settings, get_settings
from app.db.models import QuizCatalog, QuizCatalogItem
from app.quiz_bank.schemas import (
    QuizAnswerOption,
    QuizAvailabilityResponse,
    QuizCorrectAnswerReference,
    QuizItem,
    QuizQuestionsResponse,
    QuizQuestionExplanation,
    QuizSourceMetadata,
    QuizTheme,
    QuizThemesResponse,
)
from app.runtime.redis import get_shared_redis_client

LOCAL_CATALOG_CACHE_PREFIX = "dtb:local_catalog"
LOCAL_CATALOG_CACHE_TTL_SECONDS = 15
_CACHE_MISS = object()
ModelT = TypeVar("ModelT", bound=BaseModel)


class LocalCatalogNotConfiguredError(RuntimeError):
    """Raised when gameplay starts without an active local catalog."""


class LocalCatalogQuizService:
    """Quiz runtime source backed by the local PostgreSQL catalog."""

    def __init__(
        self,
        settings: Settings | None = None,
        selector: LocalCatalogSelector | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._selector = selector or LocalCatalogSelector(enabled_levels=self._settings.enabled_cefr_levels)

    async def request_quiz(
        self,
        db: AsyncSession,
        *,
        catalog_id: str | None = None,
        level: str,
        theme: str | None,
        limit: int = 1,
        user_context: Any | None = None,
        seed_material: str,
    ) -> QuizQuestionsResponse:
        if limit != 1:
            raise ValueError("Local Catalog gameplay currently selects one question at a time")
        active_catalog_id = self._catalog_id(catalog_id)
        excluded = tuple(_excluded_item_ids(user_context))
        question = await self._selector.next_question(
            db,
            CatalogQuestionRequest(
                catalog_id=active_catalog_id,
                seed_material=seed_material,
                level=level,
                theme_id=theme,
                excluded_item_ids=excluded,
            ),
        )
        items = [] if question is None else [self._to_quiz_item(question)]
        return QuizQuestionsResponse(items=items, requested_count=limit, returned_count=len(items), has_more=False)

    async def get_themes(
        self,
        db: AsyncSession,
        *,
        level: str,
        catalog_id: str | None = None,
    ) -> QuizThemesResponse:
        active_catalog_id = self._catalog_id(catalog_id)
        cache_key = self._cache_key("themes", active_catalog_id, level.upper())
        cached = await self._read_model_cache(cache_key, QuizThemesResponse)
        if cached is not None:
            return cached
        themes = await self._selector.list_themes(db, catalog_id=active_catalog_id, level=level)
        response = QuizThemesResponse(
            level=level,
            themes=[
                QuizTheme(
                    theme=theme.theme_slug or theme.theme_id,
                    theme_key=theme.theme_id,
                    is_active=True,
                    available_items_count=theme.item_count,
                    metadata={"catalog_id": active_catalog_id},
                )
                for theme in themes
            ],
            content_version=await self.catalog_version(db, catalog_id=active_catalog_id),
        )
        await self._write_model_cache(cache_key, response)
        return response

    async def get_availability(
        self,
        db: AsyncSession,
        *,
        level: str,
        theme: str,
        catalog_id: str | None = None,
    ) -> QuizAvailabilityResponse:
        active_catalog_id = self._catalog_id(catalog_id)
        cache_key = self._cache_key("availability", active_catalog_id, level.upper(), theme)
        cached = await self._read_model_cache(cache_key, QuizAvailabilityResponse)
        if cached is not None:
            return cached
        count = await self._available_count(db, catalog_id=active_catalog_id, level=level, theme=theme)
        response = QuizAvailabilityResponse(
            level=level,
            theme=theme,
            theme_key=theme,
            available_items_count=count,
            active_items_count=count,
            inactive_items_count=0,
            generated_at=datetime.now(UTC),
            content_version=await self.catalog_version(db, catalog_id=active_catalog_id),
        )
        await self._write_model_cache(cache_key, response)
        return response

    async def catalog_version(self, db: AsyncSession, *, catalog_id: str | None = None) -> str | None:
        active_catalog_id = self._catalog_id(catalog_id)
        cache_key = self._cache_key("catalog_version", active_catalog_id)
        cached = await self._read_catalog_version_cache(cache_key)
        if cached is not _CACHE_MISS:
            return cached
        statement = select(QuizCatalog.catalog_version).where(QuizCatalog.catalog_id == active_catalog_id)
        version = await db.scalar(statement)
        await self._write_catalog_version_cache(cache_key, version)
        return version

    async def _available_count(self, db: AsyncSession, *, catalog_id: str, level: str, theme: str) -> int:
        statement = (
            select(func.count())
            .select_from(QuizCatalogItem)
            .where(QuizCatalogItem.catalog_id == catalog_id)
            .where(QuizCatalogItem.language == "de")
            .where(QuizCatalogItem.level == level.upper())
            .where(or_(QuizCatalogItem.theme_id == theme, QuizCatalogItem.theme_slug == theme))
            .where(QuizCatalogItem.status.in_(self._selector.selectable_statuses))
            .where(QuizCatalogItem.is_active.is_(True))
        )
        return int((await db.scalar(statement)) or 0)

    def _catalog_id(self, value: str | None = None) -> str:
        catalog_id = (value or self._settings.active_catalog_id or "").strip()
        if not catalog_id:
            raise LocalCatalogNotConfiguredError("ACTIVE_CATALOG_ID is required for Local Catalog gameplay")
        return catalog_id

    def _cache_key(self, scope: str, *parts: str) -> str:
        return ":".join([LOCAL_CATALOG_CACHE_PREFIX, scope, *parts])

    def _cache_client(self):
        if not self._settings.local_catalog_cache_enabled:
            return None
        return get_shared_redis_client()

    async def _read_model_cache(self, cache_key: str, model_type: type[ModelT]) -> ModelT | None:
        payload = await self._read_cache_payload(cache_key)
        if payload is None:
            return None
        try:
            return model_type.model_validate_json(payload)
        except (TypeError, ValidationError, ValueError):
            return None

    async def _write_model_cache(self, cache_key: str, model: BaseModel) -> None:
        await self._write_cache_payload(cache_key, model.model_dump_json())

    async def _read_catalog_version_cache(self, cache_key: str) -> object:
        payload = await self._read_cache_payload(cache_key)
        if payload is None:
            return _CACHE_MISS
        try:
            document = json.loads(payload)
        except ValueError:
            return _CACHE_MISS
        if not isinstance(document, dict) or "catalog_version" not in document:
            return _CACHE_MISS
        cached_version = document["catalog_version"]
        if cached_version is None or isinstance(cached_version, str):
            return cached_version
        return _CACHE_MISS

    async def _write_catalog_version_cache(self, cache_key: str, catalog_version: str | None) -> None:
        await self._write_cache_payload(cache_key, json.dumps({"catalog_version": catalog_version}))

    async def _read_cache_payload(self, cache_key: str) -> str | None:
        redis_client = self._cache_client()
        if redis_client is None:
            return None
        try:
            payload = await redis_client.get(cache_key)
        except RedisError:
            return None
        if isinstance(payload, bytes):
            return payload.decode("utf-8")
        if isinstance(payload, str):
            return payload
        return None

    async def _write_cache_payload(self, cache_key: str, payload: str) -> None:
        redis_client = self._cache_client()
        if redis_client is None:
            return
        try:
            await redis_client.set(
                cache_key,
                payload,
                ex=self._settings.local_catalog_cache_ttl_seconds or LOCAL_CATALOG_CACHE_TTL_SECONDS,
            )
        except RedisError:
            return

    def _to_quiz_item(self, question: LocalCatalogQuestion) -> QuizItem:
        theme_key = question.theme_id
        metadata = dict(question.metadata or {})
        metadata.update(
            {
                "catalog_id": question.catalog_id,
                "item_version": question.item_version,
                "progress_theme_key": question.theme_slug or theme_key,
            },
        )
        return QuizItem(
            item_id=question.item_id,
            level=question.level,
            theme=question.theme_slug or theme_key,
            theme_key=theme_key,
            question_text=question.stem_text,
            answer_options=_answer_options(question.options),
            correct_answer=QuizCorrectAnswerReference(option_id=question.answer_key),
            explanation=QuizQuestionExplanation(text=question.explanation or "Keine Erklärung verfügbar."),
            metadata=metadata,
            content_version=question.item_version,
            source_metadata=QuizSourceMetadata(source="local_quiz_catalog", source_metadata=metadata),
        )


async def invalidate_local_catalog_cache(catalog_id: str, *, settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    if not settings.local_catalog_cache_enabled:
        return
    redis_client = get_shared_redis_client()
    if redis_client is None:
        return
    marker = f":{catalog_id}"
    try:
        keys = [
            key
            async for key in redis_client.scan_iter(match=f"{LOCAL_CATALOG_CACHE_PREFIX}:*")
            if isinstance(key, str) and (key.endswith(marker) or f"{marker}:" in key)
        ]
        if keys:
            await redis_client.delete(*keys)
    except RedisError:
        return


def _answer_options(options: list[object]) -> list[QuizAnswerOption]:
    return [
        QuizAnswerOption(option_id=str(index), text=str(text), order=index + 1)
        for index, text in enumerate(options)
    ]


def _excluded_item_ids(user_context: Any | None) -> list[str]:
    if user_context is None:
        return []
    if hasattr(user_context, "exclude_item_ids") and user_context.exclude_item_ids:
        return list(user_context.exclude_item_ids)
    if hasattr(user_context, "seen_item_ids") and user_context.seen_item_ids:
        return list(user_context.seen_item_ids)
    return []
