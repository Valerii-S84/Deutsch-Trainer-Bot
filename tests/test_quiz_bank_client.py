from __future__ import annotations

from typing import Any

import httpx
import pytest

from app.quiz_bank.client import QuizBankAsyncClient
from app.quiz_bank.errors import (
    QuizBankAuthError,
    QuizBankRateLimitError,
    QuizBankUnavailableError,
    QuizBankValidationError,
)


class FakeHTTPResponse:
    def __init__(self, status_code: int, payload: dict[str, Any] | list[Any] | None = None) -> None:
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.url = "https://quiz-bank.test"

    def json(self) -> dict[str, Any] | list[Any]:
        if isinstance(self._payload, (dict, list)):
            return self._payload
        raise ValueError("payload is not json")

    @property
    def text(self) -> str:
        if isinstance(self._payload, str):
            return self._payload
        if isinstance(self._payload, (dict, list)):
            return str(self._payload)
        return ""


class FakeAsyncHTTPClient:
    def __init__(self, responses: list[Any], *, raise_on_none: bool = False) -> None:
        self._responses = responses
        self.requests: list[
            tuple[
                str,
                str,
                dict[str, Any] | None,
                dict[str, str] | None,
            ]
        ] = []
        self.raise_on_none = raise_on_none

    async def request(
        self,
        *,
        method: str,
        url: str,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        timeout: float | httpx.Timeout | None = None,
    ) -> FakeHTTPResponse:
        self.requests.append((method, url, dict(params or {}), dict(headers or {})))
        if not self._responses:
            if self.raise_on_none:
                raise AssertionError("unexpected request without prepared response")
            raise httpx.TimeoutException("timeout", request=httpx.Request(method, url))
        next_item = self._responses.pop(0)
        if isinstance(next_item, Exception):
            raise next_item
        return next_item


@pytest.mark.asyncio
async def test_client_sends_auth_headers_without_secret_leakage() -> None:
    response_payload = {"items": [], "requested_count": 0, "returned_count": 0, "has_more": False}
    fake_http = FakeAsyncHTTPClient([FakeHTTPResponse(200, response_payload)])
    client = QuizBankAsyncClient(
        base_url="https://quiz-bank.test",
        edge_api_key="edge-key-123",
        consumer_api_key="consumer-key-456",
        consumer_id="consumer-1",
        timeout_seconds=1,
        max_retries=0,
        http_client=fake_http,
    )

    result = await client.fetch_questions(level="A1", theme="Artikel", limit=1)
    assert result == response_payload

    sent_headers = fake_http.requests[0][3]
    assert sent_headers["X-API-Key"] == "edge-key-123"
    assert sent_headers["X-QuizBank-API-Key"] == "consumer-key-456"
    assert sent_headers["X-Consumer-Id"] == "consumer-1"


@pytest.mark.asyncio
async def test_client_retries_transient_status_code() -> None:
    responses = [
        FakeHTTPResponse(500, {"status": "error"}),
        FakeHTTPResponse(200, {"items": [], "requested_count": 1, "returned_count": 0, "has_more": False}),
    ]
    fake_http = FakeAsyncHTTPClient(responses)
    client = QuizBankAsyncClient(
        base_url="https://quiz-bank.test",
        edge_api_key="edge-key",
        consumer_api_key="consumer-key",
        consumer_id="consumer-1",
        timeout_seconds=1,
        max_retries=1,
        http_client=fake_http,
    )
    await client.fetch_questions(level="A1", theme="Artikel", limit=1)
    assert len(fake_http.requests) == 2


@pytest.mark.asyncio
async def test_client_request_defaults_to_count_one_when_limit_missing() -> None:
    response_payload = {"items": [], "requested_count": 1, "returned_count": 0, "has_more": False}
    fake_http = FakeAsyncHTTPClient([FakeHTTPResponse(200, response_payload)])
    client = QuizBankAsyncClient(
        base_url="https://quiz-bank.test",
        edge_api_key="edge-key",
        consumer_api_key="consumer-key",
        consumer_id="consumer-1",
        timeout_seconds=1,
        max_retries=0,
        http_client=fake_http,
    )

    await client.fetch_questions(level="A1", theme="Artikel")

    sent_params = fake_http.requests[0][2]
    assert sent_params["count"] == 1


@pytest.mark.asyncio
async def test_client_retries_timeout_exception() -> None:
    fake_http = FakeAsyncHTTPClient(
        [
            httpx.TimeoutException("timeout", request=httpx.Request("GET", "https://quiz-bank.test/questions")),
            httpx.TimeoutException("timeout", request=httpx.Request("GET", "https://quiz-bank.test/questions")),
        ],
        raise_on_none=True,
    )
    client = QuizBankAsyncClient(
        base_url="https://quiz-bank.test",
        edge_api_key="edge-key",
        consumer_api_key="consumer-key",
        consumer_id="consumer-1",
        timeout_seconds=1,
        max_retries=1,
        http_client=fake_http,
    )

    with pytest.raises(QuizBankUnavailableError):
        await client.request_json("GET", "/questions", params={"level": "A1"})
    assert len(fake_http.requests) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status, expected_exception",
    [
        (401, QuizBankAuthError),
        (403, QuizBankAuthError),
        (404, QuizBankUnavailableError),
        (429, QuizBankRateLimitError),
        (503, QuizBankUnavailableError),
    ],
) 
async def test_client_error_status_maps_to_expected_exception(
    status: int,
    expected_exception: type[BaseException],
) -> None:
    fake_http = FakeAsyncHTTPClient([FakeHTTPResponse(status, {"error": "x"})], raise_on_none=True)
    client = QuizBankAsyncClient(
        base_url="https://quiz-bank.test",
        edge_api_key="edge-key",
        consumer_api_key="consumer-key",
        consumer_id="consumer-1",
        timeout_seconds=1,
        max_retries=0,
        http_client=fake_http,
    )

    with pytest.raises(expected_exception):
        await client.request_json("GET", "/questions")


@pytest.mark.asyncio
async def test_client_validation_error_when_response_json_invalid() -> None:
    fake_http = FakeAsyncHTTPClient([FakeHTTPResponse(200, ["bad", "shape"])])
    client = QuizBankAsyncClient(
        base_url="https://quiz-bank.test",
        edge_api_key="edge-key",
        consumer_api_key="consumer-key",
        consumer_id="consumer-1",
        timeout_seconds=1,
        max_retries=0,
        http_client=fake_http,
    )

    with pytest.raises(QuizBankValidationError):
        await client.request_json("GET", "/questions")


@pytest.mark.asyncio
async def test_client_exception_messages_do_not_leak_keys() -> None:
    fake_http = FakeAsyncHTTPClient([FakeHTTPResponse(503, {"error_code": "server_down", "error_message": "down"})])
    client = QuizBankAsyncClient(
        base_url="https://quiz-bank.test",
        edge_api_key="very-secret-edge-key",
        consumer_api_key="very-secret-consumer-key",
        consumer_id="consumer-1",
        timeout_seconds=1,
        max_retries=0,
        http_client=fake_http,
    )

    with pytest.raises(QuizBankUnavailableError) as exc:
        await client.request_json("GET", "/questions")

    message = str(exc.value)
    assert "very-secret-edge-key" not in message
    assert "very-secret-consumer-key" not in message
