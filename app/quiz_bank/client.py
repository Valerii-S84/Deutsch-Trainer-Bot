"""Async client for protected Quiz Bank API."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Mapping
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any
from urllib.parse import quote
from uuid import uuid4

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

logger = logging.getLogger(__name__)


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
        circuit_breaker_failure_threshold: int = 3,
        circuit_breaker_reset_seconds: int = 30,
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
        self._circuit_breaker_failure_threshold = max(1, circuit_breaker_failure_threshold)
        self._circuit_breaker_reset_seconds = max(1, circuit_breaker_reset_seconds)
        self._consecutive_transient_failures = 0
        self._circuit_open_until = 0.0
        self._http_client = http_client or httpx.AsyncClient(base_url=self._base_url, timeout=self._timeout_seconds)

    @property
    def base_url(self) -> str:
        return self._base_url

    def _headers(self, request_id: str) -> dict[str, str]:
        return {
            "X-API-Key": self._edge_api_key,
            "X-QuizBank-API-Key": self._consumer_api_key,
            "X-Consumer-Id": self._consumer_id,
            "X-Request-Id": request_id,
            "Accept": "application/json",
            "User-Agent": "deutsch-trainer-bot/0.1",
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
        json_body: Mapping[str, Any] | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> dict[str, Any]:
        self._raise_if_circuit_open(path)
        timeout = httpx.Timeout(self._timeout_seconds)
        attempt = 0
        max_attempts = max(0, self._max_retries) + 1
        can_retry = method.upper() == "GET"

        while attempt < max_attempts:
            attempt += 1
            request_id = f"qb-{uuid4().hex}"
            headers = self._headers(request_id)
            if extra_headers:
                headers.update(extra_headers)
            try:
                response = await self._http_client.request(
                    method=method,
                    url=path,
                    params=params,
                    json=dict(json_body) if json_body is not None else None,
                    headers=headers,
                    timeout=timeout,
                )
            except httpx.RequestError as exc:
                if can_retry and attempt < max_attempts:
                    await self._sleep_with_backoff(attempt, self._max_retries)
                    continue
                self._record_transient_failure(path, request_id=request_id, error_category="transport")
                raise QuizBankUnavailableError(
                    "Quiz Bank API request failed after retries",
                    request_id=request_id,
                    endpoint=path,
                ) from exc

            if response.status_code == 403 and self._problem_reason_code(response) == "CONSUMER_THEME_NOT_ALLOWED":
                self._record_permanent_error(path, response.status_code, request_id, "scope")
                raise QuizBankValidationError(
                    self._error_message(response),
                    status_code=response.status_code,
                    endpoint=path,
                    request_id=request_id,
                )

            if response.status_code == 401 or response.status_code == 403:
                self._record_permanent_error(path, response.status_code, request_id, "auth")
                raise QuizBankAuthError(
                    "Quiz Bank authentication failed",
                    status_code=response.status_code,
                    endpoint=path,
                    request_id=request_id,
                )

            if response.status_code == 404:
                self._record_permanent_error(path, response.status_code, request_id, "not_found")
                raise QuizBankUnavailableError(
                    "Quiz Bank content not found",
                    status_code=response.status_code,
                    endpoint=path,
                    request_id=request_id,
                )

            if response.status_code == 429:
                if can_retry and attempt < max_attempts:
                    await self._sleep_with_backoff(attempt, self._max_retries)
                    continue
                self._record_transient_failure(
                    path,
                    request_id=request_id,
                    status_code=response.status_code,
                    error_category="rate_limit",
                )
                raise QuizBankRateLimitError(
                    "Quiz Bank API rate limit exceeded",
                    status_code=response.status_code,
                    endpoint=path,
                    request_id=request_id,
                )

            if 500 <= response.status_code < 600:
                if can_retry and attempt < max_attempts:
                    await self._sleep_with_backoff(attempt, self._max_retries)
                    continue
                self._record_transient_failure(
                    path,
                    request_id=request_id,
                    status_code=response.status_code,
                    error_category="server",
                )
                raise QuizBankUnavailableError(
                    "Quiz Bank API server error",
                    status_code=response.status_code,
                    endpoint=path,
                    request_id=request_id,
                )

            if response.status_code >= 400:
                message = self._error_message(response)
                self._record_permanent_error(path, response.status_code, request_id, "validation")
                raise QuizBankValidationError(
                    message,
                    status_code=response.status_code,
                    endpoint=path,
                    request_id=request_id,
                )

            self._reset_circuit()
            return self._parse_json(response)

        # Defensive fallback; loop should return or raise above.
        raise QuizBankUnavailableError(
            "Quiz Bank API request was not completed",
            endpoint=path,
        )

    def _raise_if_circuit_open(self, path: str) -> None:
        if time.monotonic() < self._circuit_open_until:
            raise QuizBankUnavailableError(
                "Quiz Bank API circuit breaker is open",
                endpoint=path,
            )

    def _record_transient_failure(
        self,
        path: str,
        *,
        request_id: str,
        error_category: str,
        status_code: int | None = None,
    ) -> None:
        self._consecutive_transient_failures += 1
        if self._consecutive_transient_failures >= self._circuit_breaker_failure_threshold:
            self._circuit_open_until = time.monotonic() + self._circuit_breaker_reset_seconds
        logger.warning(
            "quiz_bank_api_error endpoint=%s status_code=%s request_id=%s category=%s",
            path,
            status_code,
            request_id,
            error_category,
        )

    def _record_permanent_error(
        self,
        path: str,
        status_code: int,
        request_id: str,
        error_category: str,
    ) -> None:
        logger.warning(
            "quiz_bank_api_error endpoint=%s status_code=%s request_id=%s category=%s",
            path,
            status_code,
            request_id,
            error_category,
        )

    def _reset_circuit(self) -> None:
        self._consecutive_transient_failures = 0
        self._circuit_open_until = 0.0

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

    def _error_message(self, response: httpx.Response) -> str:
        message = "Quiz Bank API returned an invalid request response"
        try:
            payload = self._parse_json(response)
        except QuizBankValidationError:
            return message

        try:
            error = QuizBankErrorResponse.model_validate(payload)
            return error.error_message
        except Exception:
            pass

        detail = payload.get("detail")
        title = payload.get("title")
        if isinstance(detail, str) and detail.strip():
            return detail.strip()
        if isinstance(title, str) and title.strip():
            return title.strip()
        return message

    def _problem_reason_code(self, response: httpx.Response) -> str | None:
        try:
            payload = self._parse_json(response)
        except QuizBankValidationError:
            return None
        reason_code = payload.get("reason_code")
        return reason_code.strip() if isinstance(reason_code, str) else None

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

        if limit is None:
            limit = 1

        theme_ids = await self._theme_ids_for_request(theme)
        payload = {
            "consumer_id": self._consumer_id,
            "cefr_level": level,
            "theme_ids": theme_ids,
        }
        quota_header = {"X-QuizBank-Quota-Key": self._quota_scope_key(level, theme, user_context)}
        try:
            response = await self.request_json(
                "POST",
                "/v1/quiz-items/next",
                json_body=payload,
                extra_headers=quota_header,
            )
        except QuizBankValidationError as exc:
            if not theme_ids or exc.status_code != 403:
                raise
            payload = {**payload, "theme_ids": []}
            response = await self.request_json(
                "POST",
                "/v1/quiz-items/next",
                json_body=payload,
                extra_headers=quota_header,
            )
        return self._normalize_next_quiz_response(response, requested_count=limit)

    async def fetch_health(self) -> dict[str, Any]:
        payload = await self.request_json("GET", "/v1/health")
        if "checked_at" not in payload:
            payload = {**payload, "checked_at": datetime.now(UTC).isoformat()}
        return payload

    async def fetch_levels(self) -> dict[str, Any]:
        payload = await self.request_json("GET", "/v1/levels")
        levels = []
        for item in self._data_items(payload):
            code = str(item.get("cefr_level") or item.get("code") or "").strip().upper()
            if not code:
                continue
            status = str(item.get("status") or "active").strip().lower()
            levels.append(
                {
                    "code": code,
                    "display_name": code,
                    "is_active": status == "active",
                }
            )
        return {"levels": levels}

    async def fetch_themes(
        self,
        *,
        level: str,
        include_counts: bool = True,
        active_only: bool = True,
    ) -> dict[str, Any]:
        payload = await self.request_json("GET", "/v1/topics")
        themes = []
        for item in self._data_items(payload):
            status = str(item.get("status") or "active").strip().lower()
            if active_only and status != "active":
                continue
            theme_id = str(item.get("theme_id") or item.get("topic_id") or "").strip()
            title = str(item.get("title") or "").strip()
            if not theme_id or not title:
                continue
            themes.append(
                {
                    "theme": title,
                    "theme_key": theme_id,
                    "available_items_count": 1 if include_counts and status == "active" else None,
                    "is_active": status == "active",
                    "metadata": {"theme_id": theme_id},
                }
            )
        return {"level": level.strip().upper(), "themes": themes}

    async def fetch_availability(self, *, level: str, theme: str) -> dict[str, Any]:
        return await self.request_json("GET", "/availability", params={"level": level, "theme": theme})

    async def fetch_question(self, *, item_id: str) -> dict[str, Any]:
        response = await self.request_json("GET", f"/v1/quiz-items/{quote(item_id.strip(), safe='')}")
        item = self._normalize_quiz_item_response(response)
        return {**item, "is_active": True}

    async def fetch_metadata(self) -> dict[str, Any]:
        return await self.request_json("GET", "/metadata")

    @staticmethod
    def _data_items(payload: Mapping[str, Any]) -> list[Mapping[str, Any]]:
        data = payload.get("data")
        if not isinstance(data, list):
            return []
        return [item for item in data if isinstance(item, Mapping)]

    async def _theme_ids_for_request(self, theme: str | None) -> list[str]:
        if theme is None:
            return []
        theme_value = theme.strip()
        if not theme_value:
            return []
        if self._looks_like_theme_id(theme_value):
            return [theme_value]

        topics = await self.request_json("GET", "/v1/topics")
        normalized_theme = self._normalize_key(theme_value)
        for item in self._data_items(topics):
            theme_id = str(item.get("theme_id") or item.get("topic_id") or "").strip()
            title = str(item.get("title") or "").strip()
            if not theme_id:
                continue
            candidates = {
                self._normalize_key(theme_id),
                self._normalize_key(title),
            }
            if normalized_theme in candidates:
                return [theme_id]
        return []

    @staticmethod
    def _looks_like_theme_id(value: str) -> bool:
        return len(value) == 3 and value[0].upper() == "T" and value[1:].isdigit()

    @staticmethod
    def _normalize_key(value: str) -> str:
        return " ".join(value.casefold().strip().split())

    def _quota_scope_key(
        self,
        level: str,
        theme: str | None,
        user_context: Mapping[str, Any] | None,
    ) -> str:
        context = user_context or {}
        parts = [
            "dtb",
            str(context.get("session_type") or "regular"),
            str(context.get("target_level") or level),
            str(theme or "all"),
        ]
        raw = ":".join(parts)
        digest = sha256(raw.encode("utf-8")).hexdigest()[:16]
        return f"dtb:{digest}"

    def _normalize_next_quiz_response(
        self,
        payload: Mapping[str, Any],
        *,
        requested_count: int,
    ) -> dict[str, Any]:
        item = self._normalize_quiz_item_response(payload)
        return {
            "items": [item],
            "requested_count": requested_count,
            "returned_count": 1,
            "has_more": False,
        }

    def _normalize_quiz_item_response(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        quiz_item = payload.get("quiz_item")
        if not isinstance(quiz_item, Mapping):
            raise QuizBankValidationError("Quiz Bank response is missing quiz_item")

        feedback = quiz_item.get("feedback")
        if not isinstance(feedback, Mapping):
            raise QuizBankValidationError("Quiz Bank response is missing answer feedback")

        correct_answer = str(feedback.get("correctAnswerId") or "").strip()
        if not correct_answer:
            raise QuizBankValidationError("Quiz Bank response is missing correct answer")

        question = quiz_item.get("question")
        question_text = ""
        if isinstance(question, Mapping):
            question_text = str(question.get("text") or "").strip()
        if not question_text:
            raise QuizBankValidationError("Quiz Bank response is missing question text")

        theme = quiz_item.get("theme")
        theme_title = ""
        theme_key = None
        if isinstance(theme, Mapping):
            theme_title = str(theme.get("title") or "").strip()
            theme_key = str(theme.get("slug") or "").strip() or None

        options = []
        raw_options = quiz_item.get("options")
        if isinstance(raw_options, list):
            for option in raw_options:
                if not isinstance(option, Mapping):
                    continue
                option_id = str(option.get("id") or "").strip()
                text = str(option.get("text") or "").strip()
                if not option_id or not text:
                    continue
                options.append(
                    {
                        "option_id": option_id,
                        "text": text,
                        "order": option.get("position") if isinstance(option.get("position"), int) else None,
                    }
                )

        metadata = quiz_item.get("metadata")
        if not isinstance(metadata, dict):
            metadata = {}
        progress_theme_key = theme_key or self._normalize_key(theme_title).replace(" ", "-") or "unknown"
        metadata = {**metadata, "progress_theme_key": progress_theme_key}

        return {
            "item_id": str(quiz_item.get("id") or quiz_item.get("public_id") or "").strip(),
            "level": str(quiz_item.get("cefr_level") or "").strip().upper(),
            "theme": theme_title,
            "theme_key": theme_key,
            "question_text": question_text,
            "answer_options": options,
            "correct_answer": {"option_id": correct_answer},
            "explanation": {"text": str(feedback.get("explanation") or "").strip() or "Keine Erklärung verfügbar."},
            "metadata": metadata,
            "source_metadata": {
                "source": "quiz_bank_api",
                "source_metadata": {
                    "delivery_id": payload.get("delivery_id"),
                    "consumer_id": payload.get("consumer_id"),
                },
            },
        }

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
