"""Service layer for Quiz Bank integration."""

from __future__ import annotations

from datetime import UTC, datetime
import time
from typing import TypeVar

from app.config import Settings, get_settings
from pydantic import BaseModel, ValidationError

from .client import QuizBankAsyncClient
from .errors import QuizBankError, QuizBankValidationError
from .schemas import (
    SUPPORTED_LEVELS,
    QuizAvailabilityResponse,
    QuizBankRequestContext,
    QuizHealthResponse,
    QuizLevelsResponse,
    QuizMetadataResponse,
    QuizQuestionLookupResponse,
    QuizQuestionsResponse,
    QuizThemesResponse,
)

ResponseModel = TypeVar("ResponseModel", bound=BaseModel)


class QuizBankService:
    """Business-safe Quiz Bank service used by bot flow."""

    CACHE_TTL_SECONDS = 300

    def __init__(
        self,
        client: QuizBankAsyncClient | None = None,
        settings: Settings | None = None,
        *,
        cache_ttl_seconds: int | None = None,
    ) -> None:
        if settings is None:
            settings = get_settings()
        self._client = client or QuizBankAsyncClient(
            base_url=settings.quiz_bank_api_base_url,
            edge_api_key=settings.quiz_bank_edge_api_key_or_legacy,
            consumer_api_key=settings.quiz_bank_consumer_api_key.get_secret_value()
            if settings.quiz_bank_consumer_api_key
            else None,
            consumer_id=settings.quiz_bank_consumer_id,
            timeout_seconds=settings.quiz_bank_timeout_seconds,
            max_retries=settings.quiz_bank_max_retries,
            settings=settings,
        )
        self._cache_ttl_seconds = max(1, cache_ttl_seconds or self.CACHE_TTL_SECONDS)
        self._cache: dict[str, tuple[float, BaseModel]] = {}

    async def get_health(self) -> QuizHealthResponse:
        payload = await self._client.fetch_health()
        return self._validate_payload(payload, QuizHealthResponse, "Quiz Bank health response is invalid")

    async def get_levels(self) -> QuizLevelsResponse:
        cached = self._get_cached("levels", QuizLevelsResponse)
        if cached is not None:
            return cached

        payload = await self._client.fetch_levels()
        response = self._validate_payload(payload, QuizLevelsResponse, "Quiz Bank levels response is invalid")
        filtered = [
            level
            for level in response.levels
            if level.is_active and level.code in SUPPORTED_LEVELS
        ]
        response = response.model_copy(update={"levels": filtered})
        self._set_cached("levels", response)
        return response

    async def get_themes(self, *, level: str) -> QuizThemesResponse:
        level_value = self._validate_level(level)
        cache_key = f"themes:{level_value}"
        cached = self._get_cached(cache_key, QuizThemesResponse)
        if cached is not None:
            return cached

        payload = await self._client.fetch_themes(level=level_value, include_counts=True, active_only=True)
        response = self._validate_payload(payload, QuizThemesResponse, "Quiz Bank themes response is invalid")
        filtered = [
            theme
            for theme in response.themes
            if theme.is_active and theme.available_items_count is not None and theme.available_items_count > 0
        ]
        response = response.model_copy(update={"themes": filtered})
        self._set_cached(cache_key, response)
        return response

    async def get_availability(self, *, level: str, theme: str) -> QuizAvailabilityResponse:
        level_value = self._validate_level(level)
        theme_value = self._validate_theme(theme)
        cache_key = f"availability:{level_value}:{theme_value}"
        cached = self._get_cached(cache_key, QuizAvailabilityResponse)
        if cached is not None:
            return cached

        try:
            payload = await self._client.fetch_availability(level=level_value, theme=theme_value)
        except QuizBankError as exc:
            if exc.status_code != 404:
                raise
            payload = await self._availability_from_theme_catalog(level=level_value, theme=theme_value)
        response = self._validate_payload(
            payload,
            QuizAvailabilityResponse,
            "Quiz Bank availability response is invalid",
        )
        self._set_cached(cache_key, response)
        return response

    async def _availability_from_theme_catalog(self, *, level: str, theme: str) -> dict[str, object]:
        themes = await self.get_themes(level=level)
        normalized_theme = theme.casefold()
        for item in themes.themes:
            if item.theme_key.casefold() == normalized_theme or item.theme.casefold() == normalized_theme:
                return {
                    "level": level,
                    "theme": item.theme,
                    "theme_key": item.theme_key,
                    "available_items_count": item.available_items_count or 0,
                    "generated_at": datetime.now(UTC).isoformat(),
                }
        return {
            "level": level,
            "theme": theme,
            "theme_key": theme,
            "available_items_count": 0,
            "generated_at": datetime.now(UTC).isoformat(),
        }

    async def get_question(self, *, item_id: str) -> QuizQuestionLookupResponse:
        item_id_value = item_id.strip()
        if not item_id_value:
            raise QuizBankValidationError("item_id is required")

        payload = await self._client.fetch_question(item_id=item_id_value)
        response = self._validate_payload(
            payload,
            QuizQuestionLookupResponse,
            "Quiz Bank question lookup response is invalid",
        )
        if not response.is_active:
            raise QuizBankValidationError("Quiz Bank question is not active")
        return response

    async def get_metadata(self) -> QuizMetadataResponse:
        cached = self._get_cached("metadata", QuizMetadataResponse)
        if cached is not None:
            return cached

        payload = await self._client.fetch_metadata()
        response = self._validate_payload(payload, QuizMetadataResponse, "Quiz Bank metadata response is invalid")
        self._set_cached("metadata", response)
        return response

    async def resolve_theme_ids(self, *, theme: str) -> list[str]:
        theme_value = self._validate_theme(theme)
        return await self._client._theme_ids_for_request(theme_value)

    async def request_quiz(
        self,
        *,
        level: str,
        theme: str | None,
        limit: int | None = None,
        user_context: QuizBankRequestContext | None = None,
    ) -> QuizQuestionsResponse:
        """
        Request quiz items for a given level/theme contract.

        This method validates response payload before returning it to callers.
        """
        if limit is None:
            limit = 1

        if limit <= 0:
            raise QuizBankValidationError("limit must be greater than 0")

        level_value = self._validate_level(level)

        if theme is not None:
            theme_value = self._validate_theme(theme)
        else:
            theme_value = None

        context = user_context.model_dump(exclude_none=True) if user_context else None
        payload = await self._client.fetch_questions(
            level=level_value,
            theme=theme_value,
            limit=limit,
            user_context=context,
        )
        return self._validate_payload(payload, QuizQuestionsResponse, "Quiz Bank questions response is invalid")

    def _get_cached(self, key: str, model_type: type[ResponseModel]) -> ResponseModel | None:
        item = self._cache.get(key)
        if item is None:
            return None
        expires_at, value = item
        if time.monotonic() >= expires_at:
            self._cache.pop(key, None)
            return None
        if isinstance(value, model_type):
            return value
        self._cache.pop(key, None)
        return None

    def _set_cached(self, key: str, value: BaseModel) -> None:
        self._cache[key] = (time.monotonic() + self._cache_ttl_seconds, value)

    @staticmethod
    def _validate_payload(
        payload: dict[str, object],
        model_type: type[ResponseModel],
        message: str,
    ) -> ResponseModel:
        try:
            return model_type.model_validate(payload)
        except ValidationError as exc:
            raise QuizBankValidationError(message) from exc

    @staticmethod
    def _validate_level(level: str) -> str:
        level_value = level.strip().upper()
        if not level_value:
            raise QuizBankValidationError("level is required")
        if level_value not in SUPPORTED_LEVELS:
            raise QuizBankValidationError("level is unsupported")
        return level_value

    @staticmethod
    def _validate_theme(theme: str) -> str:
        theme_value = theme.strip()
        if not theme_value:
            raise QuizBankValidationError("theme cannot be empty if provided")
        return theme_value
