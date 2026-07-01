"""Async client for protected Quiz Bank API."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote

import httpx

from app.config import Settings, get_settings

from .domain import (
    data_items,
    looks_like_theme_id,
    normalize_key,
    normalize_levels_payload,
    normalize_next_quiz_response,
    normalize_quiz_item_response,
    normalize_themes_payload,
    quota_scope_key,
)
from .errors import QuizBankConfigError, QuizBankValidationError
from .transport import QuizBankTransport, QuizBankTransportConfig


@dataclass(frozen=True)
class _ClientOptions:
    base_url: str | None
    edge_api_key: str | None
    consumer_api_key: str | None
    consumer_id: str | None
    timeout_seconds: int
    max_retries: int
    circuit_breaker_failure_threshold: int
    circuit_breaker_reset_seconds: int


def _as_str_secret(value: object) -> str | None:
    if not value:
        return None
    if hasattr(value, "get_secret_value"):
        return value.get_secret_value()  # type: ignore[call-arg]
    return str(value)


class QuizBankAsyncClient:
    """API client for Quiz Bank catalog and quiz item endpoints."""

    def __init__(
        self,
        *,
        base_url: str | None = None,
        edge_api_key: str | None = None,
        consumer_api_key: str | None = None,
        consumer_id: str | None = None,
        timeout_seconds: int = 3,
        max_retries: int = 2,
        circuit_breaker_failure_threshold: int = 3,
        circuit_breaker_reset_seconds: int = 30,
        settings: Settings | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        options = _ClientOptions(
            base_url=base_url,
            edge_api_key=edge_api_key,
            consumer_api_key=consumer_api_key,
            consumer_id=consumer_id,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
            circuit_breaker_failure_threshold=circuit_breaker_failure_threshold,
            circuit_breaker_reset_seconds=circuit_breaker_reset_seconds,
        )
        config = _transport_config(options, settings=settings)
        self._consumer_id = config.consumer_id
        self._timeout_seconds = config.timeout_seconds
        self._max_retries = config.max_retries
        self._transport = QuizBankTransport(config, http_client=http_client)

    @property
    def base_url(self) -> str:
        return self._transport.base_url

    async def close(self) -> None:
        await self._transport.close()

    async def request_json(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        json_body: Mapping[str, Any] | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> dict[str, Any]:
        return await self._transport.request_json(
            method,
            path,
            params=params,
            json_body=json_body,
            extra_headers=extra_headers,
        )

    async def fetch_questions(
        self,
        *,
        level: str,
        theme: str | None,
        limit: int | None = None,
        user_context: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        if limit is not None and limit <= 0:
            raise QuizBankValidationError("limit must be greater than 0")
        limit = limit or 1
        theme_ids = await self._theme_ids_for_request(theme)
        payload = {"consumer_id": self._consumer_id, "cefr_level": level, "theme_ids": theme_ids}
        quota_header = {"X-QuizBank-Quota-Key": quota_scope_key(level, theme, user_context)}
        try:
            response = await self.request_json("POST", "/v1/quiz-items/next", json_body=payload, extra_headers=quota_header)
        except QuizBankValidationError as exc:
            if not theme_ids or exc.status_code != 403:
                raise
            payload = {**payload, "theme_ids": []}
            response = await self.request_json("POST", "/v1/quiz-items/next", json_body=payload, extra_headers=quota_header)
        return normalize_next_quiz_response(response, requested_count=limit)

    async def fetch_health(self) -> dict[str, Any]:
        payload = await self.request_json("GET", "/v1/health")
        if "checked_at" not in payload:
            payload = {**payload, "checked_at": datetime.now(UTC).isoformat()}
        return payload

    async def fetch_levels(self) -> dict[str, Any]:
        return normalize_levels_payload(await self.request_json("GET", "/v1/levels"))

    async def fetch_themes(
        self,
        *,
        level: str,
        include_counts: bool = True,
        active_only: bool = True,
    ) -> dict[str, Any]:
        payload = await self.request_json("GET", "/v1/topics")
        return normalize_themes_payload(payload, level=level, include_counts=include_counts, active_only=active_only)

    async def fetch_availability(self, *, level: str, theme: str) -> dict[str, Any]:
        return await self.request_json("GET", "/availability", params={"level": level, "theme": theme})

    async def fetch_question(self, *, item_id: str) -> dict[str, Any]:
        response = await self.request_json("GET", f"/v1/quiz-items/{quote(item_id.strip(), safe='')}")
        return {**normalize_quiz_item_response(response), "is_active": True}

    async def fetch_metadata(self) -> dict[str, Any]:
        return await self.request_json("GET", "/metadata")

    async def _theme_ids_for_request(self, theme: str | None) -> list[str]:
        if theme is None:
            return []
        theme_value = theme.strip()
        if not theme_value:
            return []
        if looks_like_theme_id(theme_value):
            return [theme_value]

        topics = await self.request_json("GET", "/v1/topics")
        normalized_theme = normalize_key(theme_value)
        for item in data_items(topics):
            theme_id = str(item.get("theme_id") or item.get("topic_id") or "").strip()
            title = str(item.get("title") or "").strip()
            candidates = {normalize_key(theme_id), normalize_key(title)}
            if theme_id and normalized_theme in candidates:
                return [theme_id]
        return []


def _transport_config(options: _ClientOptions, *, settings: Settings | None) -> QuizBankTransportConfig:
    settings = settings or get_settings()
    resolved_base_url = options.base_url or settings.quiz_bank_api_base_url
    resolved_edge_key = options.edge_api_key or settings.quiz_bank_edge_api_key_or_legacy
    resolved_consumer_key = options.consumer_api_key or _as_str_secret(settings.quiz_bank_consumer_api_key)
    resolved_consumer_id = options.consumer_id or settings.quiz_bank_consumer_id
    resolved_timeout = options.timeout_seconds or settings.quiz_bank_timeout_seconds
    resolved_retries = options.max_retries if options.max_retries is not None else settings.quiz_bank_max_retries

    if not resolved_base_url:
        raise QuizBankConfigError("QUIZ_BANK_API_BASE_URL is required")
    if not resolved_edge_key:
        raise QuizBankConfigError("QUIZ_BANK_EDGE_API_KEY (or QUIZ_BANK_API_KEY legacy) is required")
    if not resolved_consumer_key:
        raise QuizBankConfigError("QUIZ_BANK_CONSUMER_API_KEY is required")
    if not resolved_consumer_id:
        raise QuizBankConfigError("QUIZ_BANK_CONSUMER_ID is required")

    return QuizBankTransportConfig(
        base_url=resolved_base_url.rstrip("/"),
        edge_api_key=resolved_edge_key,
        consumer_api_key=resolved_consumer_key,
        consumer_id=resolved_consumer_id,
        timeout_seconds=resolved_timeout,
        max_retries=resolved_retries,
        circuit_breaker_failure_threshold=max(1, options.circuit_breaker_failure_threshold),
        circuit_breaker_reset_seconds=max(1, options.circuit_breaker_reset_seconds),
    )
