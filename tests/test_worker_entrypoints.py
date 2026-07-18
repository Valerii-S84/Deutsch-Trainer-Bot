from __future__ import annotations

import argparse
import sys
from types import SimpleNamespace

import pytest

from app.workers import run_answer_persistence, run_outbox, run_webhook_ingress


@pytest.mark.asyncio
async def test_run_answer_persistence_once_warms_queue_prints_stats_and_cleans_up(monkeypatch, capsys) -> None:
    redis_client = object()
    queue = _AnswerQueueSpy()
    worker = _AnswerWorkerSpy(processed=3)
    cleanup = _AsyncRecorder()

    monkeypatch.setattr(run_answer_persistence, "get_settings", lambda: _answer_settings())
    monkeypatch.setattr(run_answer_persistence, "configure_logging", _Recorder())
    monkeypatch.setattr(run_answer_persistence, "create_redis_client", lambda _settings: redis_client)
    monkeypatch.setattr(run_answer_persistence, "warm_redis_client", _AsyncRecorder())
    monkeypatch.setattr(run_answer_persistence, "create_answer_persistence_queue", lambda _settings, _redis: queue)
    monkeypatch.setattr(run_answer_persistence, "AnswerPersistenceWorker", lambda **kwargs: worker.with_kwargs(kwargs))
    monkeypatch.setattr(run_answer_persistence, "close_redis_client", cleanup)
    monkeypatch.setattr(run_answer_persistence, "dispose_engine", cleanup)

    await run_answer_persistence._run(
        argparse.Namespace(
            once=True,
            batch_size=10,
            flush_interval_ms=250,
            stale_idle_ms=5000,
            max_attempts=4,
            idle_sleep_seconds=0.01,
        )
    )

    assert queue.warmed is True
    assert worker.kwargs["batch_size"] == 10
    assert "persisted=3 queue_depth=7 oldest_lag_ms=55 dead=1" in capsys.readouterr().out
    assert cleanup.calls == [(redis_client,), tuple()]


@pytest.mark.asyncio
async def test_run_answer_persistence_forever_delegates_to_worker(monkeypatch) -> None:
    redis_client = object()
    worker = _AnswerWorkerSpy(processed=0)

    monkeypatch.setattr(run_answer_persistence, "get_settings", lambda: _answer_settings(warmup=0))
    monkeypatch.setattr(run_answer_persistence, "configure_logging", lambda _level: None)
    monkeypatch.setattr(run_answer_persistence, "create_redis_client", lambda _settings: redis_client)
    monkeypatch.setattr(run_answer_persistence, "create_answer_persistence_queue", lambda _settings, _redis: _AnswerQueueSpy())
    monkeypatch.setattr(run_answer_persistence, "AnswerPersistenceWorker", lambda **kwargs: worker.with_kwargs(kwargs))
    monkeypatch.setattr(run_answer_persistence, "close_redis_client", _AsyncRecorder())
    monkeypatch.setattr(run_answer_persistence, "dispose_engine", _AsyncRecorder())

    await run_answer_persistence._run(
        argparse.Namespace(
            once=False,
            batch_size=2,
            flush_interval_ms=100,
            stale_idle_ms=1000,
            max_attempts=2,
            idle_sleep_seconds=0.25,
        )
    )

    assert worker.forever_idle_sleep_seconds == 0.25


@pytest.mark.asyncio
async def test_run_outbox_once_prints_lag_and_disposes(monkeypatch, capsys) -> None:
    worker = _OutboxWorkerSpy(processed=5, lag=1.2345)
    dispose = _AsyncRecorder()

    monkeypatch.setattr(run_outbox, "get_settings", lambda: SimpleNamespace(log_level="DEBUG"))
    monkeypatch.setattr(run_outbox, "configure_logging", _Recorder())
    monkeypatch.setattr(run_outbox, "OutboxWorker", lambda **kwargs: worker.with_kwargs(kwargs))
    monkeypatch.setattr(run_outbox, "dispose_engine", dispose)

    await run_outbox._run(
        argparse.Namespace(
            once=True,
            batch_size=25,
            parallelism=3,
            stale_after_seconds=60,
            idle_sleep_seconds=0.1,
        )
    )

    assert worker.kwargs == {"batch_size": 25, "max_parallelism": 3, "stale_after_seconds": 60}
    assert "processed=5 worker_lag_seconds=1.234" in capsys.readouterr().out
    assert dispose.calls == [tuple()]


@pytest.mark.asyncio
async def test_webhook_ingress_run_once_processes_optional_workers_and_prints_summary(monkeypatch, capsys) -> None:
    worker = _WebhookWorkerSpy(processed=2)
    queue = _QueueStatsSpy(queue_depth=9, dead_letter_length=1)
    answer_queue = _QueueStatsSpy(queue_depth=4, dead_letter_length=2)
    answer_worker = _AnswerWorkerSpy(processed=3)
    outbox_worker = _OutboxWorkerSpy(processed=1, lag=0.0)

    monkeypatch.setattr(run_webhook_ingress, "_create_answer_persistence_worker", lambda _args, _queue: answer_worker)
    monkeypatch.setattr(run_webhook_ingress, "_create_outbox_worker", lambda _args: outbox_worker)

    await run_webhook_ingress._run_once(
        argparse.Namespace(with_outbox_worker=True),
        worker=worker,
        queue=queue,
        answer_queue=answer_queue,
    )

    assert worker.processed_calls == 1
    assert answer_worker.process_once_calls == 1
    assert outbox_worker.process_once_calls == 1
    assert "processed=2 queue_depth=9 oldest_lag_ms=55 dead=1 answer_persisted=3 answer_queue_depth=4 answer_dead=2" in capsys.readouterr().out


@pytest.mark.asyncio
async def test_webhook_ingress_requires_bot_token_before_creating_redis(monkeypatch) -> None:
    redis_factory = _Recorder()
    monkeypatch.setattr(
        run_webhook_ingress,
        "get_settings",
        lambda: SimpleNamespace(log_level="INFO", bot_token=None),
    )
    monkeypatch.setattr(run_webhook_ingress, "configure_logging", lambda _level: None)
    monkeypatch.setattr(run_webhook_ingress, "create_redis_client", redis_factory)

    with pytest.raises(RuntimeError, match="BOT_TOKEN"):
        await run_webhook_ingress._run(argparse.Namespace())

    assert redis_factory.calls == []


def test_webhook_ingress_answer_queue_is_created_only_when_needed(monkeypatch) -> None:
    created = object()
    monkeypatch.setattr(run_webhook_ingress, "create_answer_persistence_queue", lambda _settings, _redis: created)

    assert run_webhook_ingress._create_answer_queue(
        argparse.Namespace(fast_answer_path=False, without_answer_persistence=False),
        SimpleNamespace(training_answer_write_behind_enabled=False),
        object(),
    ) is None
    assert run_webhook_ingress._create_answer_queue(
        argparse.Namespace(fast_answer_path=False, without_answer_persistence=True),
        SimpleNamespace(training_answer_write_behind_enabled=True),
        object(),
    ) is None
    assert run_webhook_ingress._create_answer_queue(
        argparse.Namespace(fast_answer_path=True, without_answer_persistence=True),
        SimpleNamespace(training_answer_write_behind_enabled=True),
        object(),
    ) is created


@pytest.mark.asyncio
async def test_run_webhook_ingress_once_builds_runtime_warms_workers_and_cleans_up(monkeypatch) -> None:
    redis_client = object()
    bot = _BotSpy()
    dispatcher = object()
    webhook_queue = _QueueStatsSpy(queue_depth=1, dead_letter_length=0)
    answer_queue = _QueueStatsSpy(queue_depth=2, dead_letter_length=0)
    worker = _WebhookWorkerSpy(processed=4)
    cleanup = _AsyncRecorder()
    warm = _AsyncRecorder()

    monkeypatch.setattr(run_webhook_ingress, "get_settings", lambda: _webhook_settings())
    monkeypatch.setattr(run_webhook_ingress, "configure_logging", lambda _level: None)
    monkeypatch.setattr(run_webhook_ingress, "create_redis_client", lambda _settings: redis_client)
    monkeypatch.setattr(run_webhook_ingress, "warm_redis_client", warm)
    monkeypatch.setattr(run_webhook_ingress, "create_bot", lambda token: bot.with_token(token))
    monkeypatch.setattr(run_webhook_ingress, "build_dispatcher", lambda _settings, *, redis_client: dispatcher)
    monkeypatch.setattr(run_webhook_ingress, "create_webhook_ingress_queue", lambda _settings, _redis: webhook_queue)
    monkeypatch.setattr(run_webhook_ingress, "create_answer_persistence_queue", lambda _settings, _redis: answer_queue)
    monkeypatch.setattr(run_webhook_ingress, "_create_webhook_worker", lambda _args, **_kwargs: worker)
    monkeypatch.setattr(run_webhook_ingress, "_create_answer_persistence_worker", lambda _args, _queue: _AnswerWorkerSpy(processed=5))
    monkeypatch.setattr(run_webhook_ingress, "close_redis_client", cleanup)
    monkeypatch.setattr(run_webhook_ingress, "dispose_engine", cleanup)

    await run_webhook_ingress._run(_webhook_args(once=True))

    assert warm.calls == [(redis_client,)]
    assert bot.token == "token-123"
    assert webhook_queue.warmed is True
    assert answer_queue.warmed is True
    assert worker.processed_calls == 1
    assert bot.session.closed is True
    assert cleanup.calls == [(redis_client,), tuple()]


def test_run_webhook_ingress_main_applies_settings_defaults(monkeypatch) -> None:
    captured = _RunCapture()
    monkeypatch.setattr(sys, "argv", ["run_webhook_ingress", "--once", "--without-answer-persistence"])
    monkeypatch.setattr(run_webhook_ingress, "get_settings", lambda: _webhook_settings())
    monkeypatch.setattr(run_webhook_ingress, "_run", captured)
    monkeypatch.setattr(run_webhook_ingress.asyncio, "run", lambda awaitable: awaitable.close())

    run_webhook_ingress.main()

    args = captured.args
    assert args is not None
    assert args.once is True
    assert args.without_answer_persistence is True
    assert args.batch_size == 11
    assert args.parallelism == 3
    assert args.block_ms == 50
    assert args.stale_idle_ms == 6000
    assert args.max_attempts == 4
    assert args.fast_answer_path is True
    assert args.answer_persist_batch_size == 12
    assert args.answer_persist_flush_interval_ms == 90
    assert args.answer_persist_stale_idle_ms == 7000
    assert args.answer_persist_max_attempts == 5


def test_run_answer_persistence_main_applies_settings_defaults(monkeypatch) -> None:
    captured = _RunCapture()
    monkeypatch.setattr(sys, "argv", ["run_answer_persistence", "--once"])
    monkeypatch.setattr(
        run_answer_persistence,
        "get_settings",
        lambda: SimpleNamespace(
            answer_persist_batch_size=21,
            answer_persist_flush_interval_ms=120,
            answer_persist_stale_idle_ms=8000,
            answer_persist_max_attempts=6,
        ),
    )
    monkeypatch.setattr(run_answer_persistence, "_run", captured)
    monkeypatch.setattr(run_answer_persistence.asyncio, "run", lambda awaitable: awaitable.close())

    run_answer_persistence.main()

    args = captured.args
    assert args is not None
    assert args.once is True
    assert args.batch_size == 21
    assert args.flush_interval_ms == 120
    assert args.stale_idle_ms == 8000
    assert args.max_attempts == 6


def test_run_outbox_main_passes_cli_values_to_worker(monkeypatch) -> None:
    captured = _RunCapture()
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_outbox",
            "--once",
            "--batch-size",
            "33",
            "--parallelism",
            "4",
            "--stale-after-seconds",
            "99",
        ],
    )
    monkeypatch.setattr(run_outbox, "_run", captured)
    monkeypatch.setattr(run_outbox.asyncio, "run", lambda awaitable: awaitable.close())

    run_outbox.main()

    args = captured.args
    assert args is not None
    assert args.once is True
    assert args.batch_size == 33
    assert args.parallelism == 4
    assert args.stale_after_seconds == 99


class _AnswerWorkerSpy:
    def __init__(self, *, processed: int) -> None:
        self.processed = processed
        self.kwargs: dict[str, object] = {}
        self.process_once_calls = 0
        self.forever_idle_sleep_seconds: float | None = None

    def with_kwargs(self, kwargs: dict[str, object]):
        self.kwargs = kwargs
        return self

    async def process_once(self) -> int:
        self.process_once_calls += 1
        return self.processed

    async def run_forever(self, *, idle_sleep_seconds: float) -> None:
        self.forever_idle_sleep_seconds = idle_sleep_seconds


class _OutboxWorkerSpy:
    def __init__(self, *, processed: int, lag: float) -> None:
        self.processed = processed
        self.lag = lag
        self.kwargs: dict[str, object] = {}
        self.process_once_calls = 0

    def with_kwargs(self, kwargs: dict[str, object]):
        self.kwargs = kwargs
        return self

    async def process_once(self) -> int:
        self.process_once_calls += 1
        return self.processed

    async def lag_seconds(self) -> float:
        return self.lag


class _WebhookWorkerSpy:
    def __init__(self, *, processed: int) -> None:
        self.processed = processed
        self.processed_calls = 0

    async def process_once(self) -> int:
        self.processed_calls += 1
        return self.processed

    async def run_forever(self, *, idle_sleep_seconds: float) -> None:
        self.idle_sleep_seconds = idle_sleep_seconds


class _AnswerQueueSpy:
    def __init__(self) -> None:
        self.warmed = False

    async def warm(self) -> None:
        self.warmed = True

    async def stats(self):
        return _stats(queue_depth=7, dead_letter_length=1)


class _QueueStatsSpy:
    def __init__(self, *, queue_depth: int, dead_letter_length: int) -> None:
        self._queue_depth = queue_depth
        self._dead_letter_length = dead_letter_length
        self.warmed = False

    async def warm(self) -> None:
        self.warmed = True

    async def stats(self):
        return _stats(queue_depth=self._queue_depth, dead_letter_length=self._dead_letter_length)


class _AsyncRecorder:
    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []

    async def __call__(self, *args: object, **_kwargs: object) -> None:
        self.calls.append(args)


class _Recorder:
    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []

    def __call__(self, *args: object, **_kwargs: object) -> None:
        self.calls.append(args)


def _answer_settings(*, warmup: int = 2):
    return SimpleNamespace(
        log_level="INFO",
        redis_warmup_connections=warmup,
        redis_max_connections=5,
    )


def _webhook_settings():
    return SimpleNamespace(
        log_level="INFO",
        bot_token=_Secret("token-123"),
        redis_warmup_connections=2,
        redis_max_connections=10,
        training_answer_write_behind_enabled=True,
        webhook_ingress_worker_batch_size=11,
        webhook_ingress_worker_parallelism=3,
        webhook_ingress_read_block_ms=50,
        webhook_ingress_stale_idle_ms=6000,
        webhook_ingress_max_attempts=4,
        webhook_ingress_fast_answer_path=True,
        answer_persist_batch_size=12,
        answer_persist_flush_interval_ms=90,
        answer_persist_stale_idle_ms=7000,
        answer_persist_max_attempts=5,
    )


def _webhook_args(*, once: bool):
    return argparse.Namespace(
        once=once,
        batch_size=11,
        parallelism=3,
        block_ms=50,
        stale_idle_ms=6000,
        max_attempts=4,
        idle_sleep_seconds=0.1,
        initial_delay_seconds=0.0,
        without_answer_persistence=False,
        fast_answer_path=True,
        with_outbox_worker=False,
        outbox_batch_size=200,
        outbox_parallelism=5,
        outbox_stale_after_seconds=300,
        outbox_idle_sleep_seconds=1.0,
        answer_persist_batch_size=12,
        answer_persist_flush_interval_ms=90,
        answer_persist_stale_idle_ms=7000,
        answer_persist_max_attempts=5,
        answer_persist_idle_sleep_seconds=0.02,
    )


class _Secret:
    def __init__(self, value: str) -> None:
        self._value = value

    def get_secret_value(self) -> str:
        return self._value


class _BotSpy:
    def __init__(self) -> None:
        self.token: str | None = None
        self.session = _BotSessionSpy()

    def with_token(self, token: str):
        self.token = token
        return self


class _BotSessionSpy:
    def __init__(self) -> None:
        self.closed = False

    async def close(self) -> None:
        self.closed = True


class _RunCapture:
    def __init__(self) -> None:
        self.args = None

    def __call__(self, args):
        self.args = args
        return _ClosableAwaitable()


class _ClosableAwaitable:
    def close(self) -> None:
        return None


def _stats(*, queue_depth: int, dead_letter_length: int):
    return SimpleNamespace(
        queue_depth=queue_depth,
        oldest_lag_ms=55,
        dead_letter_length=dead_letter_length,
    )
