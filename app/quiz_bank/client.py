"""Async client for protected Quiz Bank API."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any

import httpx

from app.config import Settings, get_settings

from .errors import (
    QuizBankAuthError,
    QuizBankConfigError,
    QuizBankRateLimitError,
    QuizBankUnavailableError,
    QuizBankValidationError,
)
from .schemas import QuizBankErrorResponse


def _as_str_secret(value: object) -> str | None:
    if not value:
        return None
    if hasattr(value, "get_secret_value"):
        return value.get_secret_value()  # type: ignore[call-arg]
    return str(value)


class QuizBankAsyncClient:
    """HTTP client with timeout and retry policy for protected Quiz Bank API."""

    def __init__(
        self,
        *,
        base_url: str | None = None,
        edge_api_key: str | None = None,
        consumer_api_key: str | None = None,
        consumer_id: str | None = None,
        timeout_seconds: int = 3,
        max_retries: int = 2,
        settings: Settings | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        if settings is None:
            settings = get_settings()

        resolved_base_url = base_url or settings.quiz_bank_api_base_url
        resolved_edge_key = edge_api_key or settings.quiz_bank_edge_api_key_or_legacy
        resolved_consumer_key = consumer_api_key or _as_str_secret(settings.quiz_bank_consumer_api_key)
        resolved_consumer_id = consumer_id or settings.quiz_bank_consumer_id
        resolved_timeout = timeout_seconds or settings.quiz_bank_timeout_seconds
        resolved_retries = max_retries if max_retries is not None else settings.quiz_bank_max_retries

        if not resolved_base_url:
            raise QuizBankConfigError("QUIZ_BANK_API_BASE_URL is required")
        if not resolved_edge_key:
            raise QuizBankConfigError(
                "QUIZ_BANK_EDGE_API_KEY (or QUIZ_BANK_API_KEY legacy) is required",
            )
        if not resolved_consumer_key:
            raise QuizBankConfigError("QUIZ_BANK_CONSUMER_API_KEY is required")
        if not resolved_consumer_id:
            raise QuizBankConfigError("QUIZ_BANK_CONSUMER_ID is required")

        self._base_url = resolved_base_url.rstrip("/")
        self._edge_api_key = resolved_edge_key
        self._consumer_api_key = resolved_consumer_key
        self._consumer_id = resolved_consumer_id
        self._timeout_seconds = resolved_timeout
        self._max_retries = resolved_retries
        self._http_client = http_client or httpx.AsyncClient(base_url=self._base_url, timeout=self._timeout_seconds)

    @property
    def base_url(self) -> str:
        return self._base_url

    def _auth_headers(self) -> dict[str, str]:
        return {
            "X-API-Key": self._edge_api_key,
            "X-QuizBank-API-Key": self._consumer_api_key,
            "X-Consumer-Id": self._consumer_id,
        }

    async def close(self) -> None:
        if hasattr(self._http_client, "aclose"):
            await self._http_client.aclose()

    async def request_json(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        timeout = httpx.Timeout(self._timeout_seconds)
        attempt = 0
        max_attempts = max(0, self._max_retries) + 1

        while attempt < max_attempts:
            attempt += 1
            request_id = f"qb-{attempt}-{id(self)}"
            try:
                response = await self._http_client.request(
                    method=method,
                    url=path,
                    params=params,
                    headers=self._auth_headers(),
                    timeout=timeout,
                )
            except httpx.RequestError as exc:
                if attempt < max_attempts:
                    await self._sleep_with_backoff(attempt, self._max_retries)
                    continue
                raise QuizBankUnavailableError(
                    "Quiz Bank API request failed after retries",
                    request_id=request_id,
                    endpoint=path,
                ) from exc

            if response.status_code == 401 or response.status_code == 403:
                raise QuizBankAuthError(
                    "Quiz Bank authentication failed",
                    status_code=response.status_code,
                    endpoint=path,
                    request_id=request_id,
                )

            if response.status_code == 404:
                raise QuizBankUnavailableError(
                    "Quiz Bank content not found",
                    status_code=response.status_code,
                    endpoint=path,
                    request_id=request_id,
                )

            if response.status_code == 429:
                if attempt < max_attempts:
                    await self._sleep_with_backoff(attempt, self._max_retries)
                    continue
                raise QuizBankRateLimitError(
                    "Quiz Bank API rate limit exceeded",
                    status_code=response.status_code,
                    endpoint=path,
                    request_id=request_id,
                )

            if 500 <= response.status_code < 600:
                if attempt < max_attempts:
                    await self._sleep_with_backoff(attempt, self._max_retries)
                    continue
                raise QuizBankUnavailableError(
                    "Quiz Bank API server error",
                    status_code=response.status_code,
                    endpoint=path,
                    request_id=request_id,
                )

            if response.status_code >= 400:
                message = "Quiz Bank API returned an invalid request response"
                try:
                    payload = self._parse_json(response)
                    error = QuizBankErrorResponse.model_validate(payload)
                    message = error.error_message
                except QuizBankValidationError:
                    pass
                except Exception:
                    message = "Quiz Bank API returned invalid JSON error response"
                raise QuizBankValidationError(
                    message,
                    status_code=response.status_code,
                    endpoint=path,
                    request_id=request_id,
                )

            return self._parse_json(response)

        # Defensive fallback; loop should return or raise above.
        raise QuizBankUnavailableError(
            "Quiz Bank API request was not completed",
            endpoint=path,
        )

    async def _sleep_with_backoff(self, attempt: int, max_retries: int) -> None:
        delay = 0.05 * (2 ** (attempt - 1))
        if attempt > max_retries:
            return
        await asyncio.sleep(delay)

    def _parse_json(self, response: httpx.Response) -> dict[str, Any]:
        try:
            data = response.json()
        except ValueError as exc:
            raise QuizBankValidationError(
                "Quiz Bank API returned invalid JSON",
                status_code=response.status_code,
                endpoint=str(response.url),
            ) from exc
        if not isinstance(data, dict):
            raise QuizBankValidationError(
                "Quiz Bank API response must be a JSON object",
                status_code=response.status_code,
                endpoint=str(response.url),
            )
        return data

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

        params = {"level": level, "count": limit}
        if theme:
            params["theme"] = theme
        if user_context:
            params.update(self._compact_context(user_context))
        if limit is None:
            params["count"] = 1

        return await self.request_json("GET", "/questions", params=params)

    def _compact_context(self, user_context: Mapping[str, Any]) -> dict[str, Any]:
        items: dict[str, Any] = {}
        for key in (
            "session_type",
            "seen_item_ids",
            "mistake_item_ids",
            "weak_theme_keys",
            "target_level",
            "item_ids",
            "exclude_seen",
            "exclude_item_ids",
        ):
            value = user_context.get(key)
            if value is None:
                continue
            if isinstance(value, (list, tuple)) and not value:
                continue
            items[key] = value
        return items
