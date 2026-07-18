"""Transport layer for protected Quiz Bank API requests."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

import httpx
from pydantic import ValidationError

from .errors import (
    QuizBankAuthError,
    QuizBankRateLimitError,
    QuizBankUnavailableError,
    QuizBankValidationError,
)
from .schemas import QuizBankErrorResponse

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class QuizBankTransportConfig:
    base_url: str
    edge_api_key: str
    consumer_api_key: str
    consumer_id: str
    timeout_seconds: int
    max_retries: int
    circuit_breaker_failure_threshold: int
    circuit_breaker_reset_seconds: int


class QuizBankTransport:
    """HTTP transport with retry, timeout, and circuit breaker policy."""

    def __init__(self, config: QuizBankTransportConfig, *, http_client: httpx.AsyncClient | None = None) -> None:
        self._config = config
        self._consecutive_transient_failures = 0
        self._circuit_open_until = 0.0
        self._http_client = http_client or httpx.AsyncClient(
            base_url=config.base_url,
            timeout=config.timeout_seconds,
        )

    @property
    def base_url(self) -> str:
        return self._config.base_url

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
        max_attempts = max(0, self._config.max_retries) + 1
        can_retry = method.upper() == "GET"
        for attempt in range(1, max_attempts + 1):
            request_id = f"qb-{uuid4().hex}"
            try:
                response = await self._send(method, path, request_id, params, json_body, extra_headers)
            except httpx.RequestError as exc:
                if await self._retry_if_allowed(can_retry=can_retry, attempt=attempt, max_attempts=max_attempts):
                    continue
                self._record_transient_failure(path, request_id=request_id, error_category="transport")
                raise QuizBankUnavailableError(
                    "Quiz Bank API request failed after retries",
                    request_id=request_id,
                    endpoint=path,
                ) from exc
            if await self._retry_if_allowed(
                can_retry=can_retry,
                attempt=attempt,
                max_attempts=max_attempts,
                status_code=response.status_code,
            ):
                continue
            self._raise_for_error_response(response, path=path, request_id=request_id)
            self._reset_circuit()
            return self._parse_json(response)
        raise QuizBankUnavailableError("Quiz Bank API request was not completed", endpoint=path)

    async def _send(
        self,
        method: str,
        path: str,
        request_id: str,
        params: Mapping[str, Any] | None,
        json_body: Mapping[str, Any] | None,
        extra_headers: Mapping[str, str] | None,
    ) -> httpx.Response:
        headers = self._headers(request_id)
        if extra_headers:
            headers.update(extra_headers)
        return await self._http_client.request(
            method=method,
            url=path,
            params=params,
            json=dict(json_body) if json_body is not None else None,
            headers=headers,
            timeout=httpx.Timeout(self._config.timeout_seconds),
        )

    def _headers(self, request_id: str) -> dict[str, str]:
        return {
            "X-API-Key": self._config.edge_api_key,
            "X-QuizBank-API-Key": self._config.consumer_api_key,
            "X-Consumer-Id": self._config.consumer_id,
            "X-Request-Id": request_id,
            "Accept": "application/json",
            "User-Agent": "deutsch-trainer-bot/0.1",
        }

    async def _retry_if_allowed(
        self,
        *,
        can_retry: bool,
        attempt: int,
        max_attempts: int,
        status_code: int | None = None,
    ) -> bool:
        if not can_retry or attempt >= max_attempts:
            return False
        if status_code is not None and status_code != 429 and not 500 <= status_code < 600:
            return False
        await self._sleep_with_backoff(attempt)
        return True

    async def _sleep_with_backoff(self, attempt: int) -> None:
        if attempt > self._config.max_retries:
            return
        await asyncio.sleep(0.05 * (2 ** (attempt - 1)))

    def _raise_for_error_response(self, response: httpx.Response, *, path: str, request_id: str) -> None:
        status = response.status_code
        context = {"status_code": status, "endpoint": path, "request_id": request_id}
        if status == 403 and self._problem_reason_code(response) == "CONSUMER_THEME_NOT_ALLOWED":
            self._record_permanent_error(path, status, request_id, "scope")
            raise QuizBankValidationError(self._error_message(response), **context)
        if status == 401 or status == 403:
            self._record_permanent_error(path, status, request_id, "auth")
            raise QuizBankAuthError("Quiz Bank authentication failed", **context)
        if status == 404:
            self._record_permanent_error(path, status, request_id, "not_found")
            raise QuizBankUnavailableError("Quiz Bank content not found", **context)
        if status == 429:
            self._record_transient_failure(path, request_id=request_id, status_code=status, error_category="rate_limit")
            raise QuizBankRateLimitError("Quiz Bank API rate limit exceeded", **context)
        if 500 <= status < 600:
            self._record_transient_failure(path, request_id=request_id, status_code=status, error_category="server")
            raise QuizBankUnavailableError("Quiz Bank API server error", **context)
        if status >= 400:
            self._record_permanent_error(path, status, request_id, "validation")
            raise QuizBankValidationError(self._error_message(response), **context)

    def _raise_if_circuit_open(self, path: str) -> None:
        if time.monotonic() < self._circuit_open_until:
            raise QuizBankUnavailableError("Quiz Bank API circuit breaker is open", endpoint=path)

    def _record_transient_failure(
        self,
        path: str,
        *,
        request_id: str,
        error_category: str,
        status_code: int | None = None,
    ) -> None:
        self._consecutive_transient_failures += 1
        if self._consecutive_transient_failures >= self._config.circuit_breaker_failure_threshold:
            self._circuit_open_until = time.monotonic() + self._config.circuit_breaker_reset_seconds
        logger.warning(
            "quiz_bank_api_error endpoint=%s status_code=%s request_id=%s category=%s",
            path,
            status_code,
            request_id,
            error_category,
        )

    def _record_permanent_error(self, path: str, status_code: int, request_id: str, error_category: str) -> None:
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
        except ValidationError:
            return message

    def _problem_reason_code(self, response: httpx.Response) -> str | None:
        try:
            payload = self._parse_json(response)
        except QuizBankValidationError:
            return None
        reason_code = payload.get("reason_code")
        return reason_code.strip() if isinstance(reason_code, str) else None
