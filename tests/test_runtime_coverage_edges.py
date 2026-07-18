from __future__ import annotations

from types import SimpleNamespace

from aiogram import Bot
from aiogram.methods import DeleteMessage, SendMessage
import pytest

from app.runtime.fake_telegram import FakeTelegramSession, _int_chat_id
from app.runtime.webhook_handler import ProfiledSimpleRequestHandler
from app.runtime.webhook_profiling import (
    WebhookProfileCollector,
    begin_webhook_timing,
    current_webhook_operation_label,
    end_webhook_timing,
    merge_webhook_metrics,
    merge_webhook_timings,
    record_webhook_metric,
    webhook_operation_label,
    webhook_timing_span,
)


@pytest.mark.asyncio
async def test_fake_telegram_session_returns_real_message_model_and_bool_methods() -> None:
    session = FakeTelegramSession()
    bot = Bot(token="123:ABC", session=session)

    sent = await session.make_request(bot, SendMessage(chat_id="700001", text="Hallo"))
    deleted = await session.make_request(bot, DeleteMessage(chat_id=700001, message_id=sent.message_id))

    assert sent.message_id == 1
    assert sent.chat.id == 700001
    assert sent.text == "Hallo"
    assert deleted is True


@pytest.mark.asyncio
async def test_fake_telegram_session_rejects_unsupported_streaming() -> None:
    session = FakeTelegramSession()

    with pytest.raises(RuntimeError, match="stream_content"):
        async for _chunk in session.stream_content("https://example.test/file"):
            pass


def test_fake_telegram_chat_id_normalization_is_safe_for_bad_values() -> None:
    assert _int_chat_id(42) == 42
    assert _int_chat_id("42") == 42
    assert _int_chat_id(None) == 0
    assert _int_chat_id("not-an-id") == 0


@pytest.mark.asyncio
async def test_profiled_webhook_handler_records_unauthorized_requests() -> None:
    profiler = _ProfilerSpy()
    handler = object.__new__(ProfiledSimpleRequestHandler)
    handler._profiler = profiler
    handler.resolve_bot = _async_return(SimpleNamespace())  # type: ignore[method-assign]
    handler.verify_secret = lambda _secret, _bot: False  # type: ignore[method-assign]

    response = await handler.handle(_RequestStub(path="/telegram/webhook", secret="wrong"))

    assert response.status == 401
    assert profiler.requests[0]["status_code"] == 401
    assert profiler.requests[0]["request_path"] == "/telegram/webhook"
    assert "webhook.resolve_bot_ms" in profiler.requests[0]["spans_ms"]
    assert "webhook.verify_secret_ms" in profiler.requests[0]["spans_ms"]


@pytest.mark.asyncio
async def test_profiled_webhook_handler_dispatches_json_and_records_success() -> None:
    profiler = _ProfilerSpy()
    dispatcher = _DispatcherSpy(result={"ok": True})
    bot = SimpleNamespace(session=SimpleNamespace(json_loads=lambda value: value))
    handler = object.__new__(ProfiledSimpleRequestHandler)
    handler._profiler = profiler
    handler.dispatcher = dispatcher
    handler.data = {"source": "test"}
    handler.handle_in_background = False
    handler.resolve_bot = _async_return(bot)  # type: ignore[method-assign]
    handler.verify_secret = lambda _secret, _bot: True  # type: ignore[method-assign]
    handler._build_response_writer = lambda **_kwargs: b"ok"  # type: ignore[method-assign]

    response = await handler.handle(_RequestStub(path="/telegram/webhook", secret="secret", payload={"update_id": 101}))

    assert response.status == 200
    assert response.body == b"ok"
    assert dispatcher.calls == [(bot, {"update_id": 101}, {"source": "test"})]
    assert profiler.requests[0]["status_code"] == 200
    assert "webhook.request_json_ms" in profiler.requests[0]["spans_ms"]
    assert "webhook.dispatch_ms" in profiler.requests[0]["spans_ms"]
    assert "webhook.response_build_ms" in profiler.requests[0]["spans_ms"]


def test_webhook_timing_context_merges_nested_metrics_and_restores_label() -> None:
    timings, metrics, token = begin_webhook_timing()
    try:
        with webhook_timing_span("outer_ms"):
            pass
        merge_webhook_timings({"db_ms": 1.25, "outer_ms": 0.75})
        record_webhook_metric("redis.command_count", 1)
        merge_webhook_metrics({"redis.command_count": 2, "redis.command_ms": 3.5})

        with webhook_operation_label("answer"):
            assert current_webhook_operation_label() == "answer"
        assert current_webhook_operation_label() is None
    finally:
        end_webhook_timing(token)

    assert timings["outer_ms"] >= 0.75
    assert timings["db_ms"] == 1.25
    assert metrics == {"redis.command_count": 3.0, "redis.command_ms": 3.5}


def test_webhook_profile_collector_writes_latency_summary_with_status_and_slowest_requests(tmp_path) -> None:
    output_path = tmp_path / "latency.json"
    collector = WebhookProfileCollector(
        latency_output_path=str(output_path),
        cpu_output_path=None,
        cpu_interval_ms=10.0,
    )

    collector.start()
    collector.record_request(
        request_path="/telegram/webhook",
        status_code=200,
        total_ms=30.1239,
        spans_ms={"webhook.dispatch_ms": 20.0, "handler.training_answer_submit_ms": 5.0},
        metrics={"redis.command_count": 2},
    )
    collector.record_request(
        request_path="/telegram/webhook",
        status_code=503,
        total_ms=90.0,
        spans_ms={"webhook.dispatch_ms": 80.0},
        metrics={"redis.command_count": 4},
    )
    collector.close()

    payload = output_path.read_text(encoding="utf-8")
    assert '"request_count": 2' in payload
    assert '"200": 1' in payload
    assert '"503": 1' in payload
    assert '"redis.command_count": 4.0' in payload
    assert '"slowest_requests"' in payload


@pytest.mark.asyncio
async def test_driver_profiling_records_redis_driver_metrics(monkeypatch) -> None:
    from redis.asyncio.client import Redis
    from redis.asyncio.connection import Connection, ConnectionPool

    import app.runtime.driver_profiling as profiling

    profiling._redis_profiling_installed = False
    metrics: list[tuple[str, float | int]] = []

    async def execute_command(_self, *_args, **_kwargs):
        return "PONG"

    async def get_connection(self, *_args, **_kwargs):
        self._available_connections.append(object())
        return "connection"

    async def connect(_self, *_args, **_kwargs):
        return None

    async def read_response(_self, *_args, **_kwargs):
        return "response"

    monkeypatch.setattr(Redis, "execute_command", execute_command)
    monkeypatch.setattr(ConnectionPool, "get_connection", get_connection)
    monkeypatch.setattr(Connection, "_connect", connect)
    monkeypatch.setattr(Connection, "read_response", read_response)
    monkeypatch.setattr(profiling, "current_webhook_operation_label", lambda: "redis")
    monkeypatch.setattr(profiling, "record_webhook_metric", lambda name, value: metrics.append((name, value)))

    profiling.install_redis_profiling()
    pool = SimpleNamespace(_available_connections=[], _in_use_connections=[])

    assert await Redis.execute_command(object(), "PING") == "PONG"
    assert await ConnectionPool.get_connection(pool, "PING") == "connection"
    assert await Connection._connect(object()) is None
    assert await Connection.read_response(object()) == "response"

    metric_names = {name for name, _value in metrics}
    assert "redis.command_ms" in metric_names
    assert "redis.command_count" in metric_names
    assert "redis.pool_new_connection_count" in metric_names
    assert "redis.pool_acquire_ms" in metric_names
    assert "redis.connect_ms" in metric_names
    assert "redis.read_response_ms" in metric_names


@pytest.mark.asyncio
async def test_driver_profiling_records_sqlalchemy_prepare_and_transaction_metrics(monkeypatch) -> None:
    from sqlalchemy.dialects.postgresql.asyncpg import AsyncAdapt_asyncpg_connection

    import app.runtime.driver_profiling as profiling

    profiling._sqlalchemy_asyncpg_profiling_installed = False
    metrics: list[tuple[str, float | int]] = []

    async def prepare(_self, operation: str, invalidate_timestamp: float):
        return f"{operation}:{invalidate_timestamp}"

    async def start_transaction(_self):
        return "started"

    monkeypatch.setattr(AsyncAdapt_asyncpg_connection, "_prepare", prepare)
    monkeypatch.setattr(AsyncAdapt_asyncpg_connection, "_start_transaction", start_transaction)
    monkeypatch.setattr(profiling, "current_timing_query_label", lambda: "query")
    monkeypatch.setattr(profiling, "record_timing_metric", lambda name, value: metrics.append((name, value)))

    profiling.install_sqlalchemy_asyncpg_profiling()

    assert await AsyncAdapt_asyncpg_connection._prepare(object(), "select 1", 0.0) == "select 1:0.0"
    assert await AsyncAdapt_asyncpg_connection._start_transaction(object()) == "started"
    metric_names = {name for name, _value in metrics}
    assert {"query.prepare_ms", "query.prepare_count", "query.tx_start_ms", "query.tx_start_count"} <= metric_names


class _ProfilerSpy:
    def __init__(self) -> None:
        self.requests: list[dict[str, object]] = []

    def record_request(self, **kwargs: object) -> None:
        self.requests.append(kwargs)


class _DispatcherSpy:
    def __init__(self, *, result: object) -> None:
        self._result = result
        self.calls: list[tuple[object, object, dict[str, object]]] = []

    async def feed_webhook_update(self, bot: object, update: object, **kwargs: object) -> object:
        self.calls.append((bot, update, kwargs))
        return self._result


class _RequestStub:
    def __init__(self, *, path: str, secret: str, payload: object | None = None) -> None:
        self.path = path
        self.headers = {"X-Telegram-Bot-Api-Secret-Token": secret}
        self._payload = payload or {}

    async def json(self, *, loads):
        return loads(self._payload)


def _async_return(value: object):
    async def _inner(*_args: object, **_kwargs: object) -> object:
        return value

    return _inner
