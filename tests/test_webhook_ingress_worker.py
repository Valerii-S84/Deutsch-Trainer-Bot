from __future__ import annotations

from aiogram import Bot
from aiogram.types import Update
import pytest
from redis.exceptions import RedisError

from app.runtime.fake_telegram import FakeTelegramSession
from app.runtime.webhook_ingress_queue import WebhookStreamMessage
from app.services.training_payloads import AnswerResult
from app.workers.webhook_ingress import WebhookIngressWorker, WebhookIngressWorkerConfig


@pytest.mark.asyncio
async def test_webhook_ingress_worker_uses_plain_update_dispatch() -> None:
    dispatcher = _DispatcherSpy()
    worker = WebhookIngressWorker(
        bot=Bot(token="123:ABC", session=FakeTelegramSession()),
        dispatcher=dispatcher,
        queue=_QueueStub(),
    )
    message = WebhookStreamMessage(
        message_id="1-0",
        update_id=42,
        payload={
            "update_id": 42,
            "message": {
                "message_id": 1,
                "date": 1_720_000_000,
                "chat": {"id": 1001, "type": "private"},
                "from": {"id": 1001, "is_bot": False, "first_name": "Ada"},
                "text": "/start",
            },
        },
        enqueued_at_ms=1,
        attempt=0,
    )

    processed = await worker._process_message(message)

    assert processed is not None
    assert processed[0] is message
    assert processed[1] >= 0.0
    assert dispatcher.feed_webhook_update_called is False
    assert isinstance(dispatcher.update, Update)
    assert dispatcher.kwargs == {
        "skip_backpressure": True,
        "skip_duplicate_guard": True,
        "skip_rate_limit": True,
    }


@pytest.mark.asyncio
async def test_webhook_ingress_worker_marks_completed_messages_incrementally() -> None:
    queue = _BatchQueueStub(
        [
            _message(101),
            _message(102),
        ]
    )
    worker = WebhookIngressWorker(
        bot=Bot(token="123:ABC", session=FakeTelegramSession()),
        dispatcher=_DispatcherSpy(),
        queue=queue,
        config=WebhookIngressWorkerConfig(max_parallelism=1),
    )

    processed = await worker.process_once()

    assert processed == 2
    assert len(queue.marked_update_ids) == 2
    assert all(len(update_ids) == 1 for update_ids in queue.marked_update_ids)
    assert sorted(update_ids[0] for update_ids in queue.marked_update_ids) == [101, 102]


@pytest.mark.asyncio
async def test_webhook_ingress_worker_batches_fast_answer_callbacks(monkeypatch) -> None:
    queue = _BatchQueueStub([_callback_message(101, 1, "tok1"), _callback_message(102, 2, "tok2")])
    requests = []

    async def accept_many(*, queue, requests: list[object]):
        del queue
        return [_answer_result(request.session_id) for request in requests]

    def capture_accept_many(**kwargs):
        requests.extend(kwargs["requests"])
        return accept_many(**kwargs)

    monkeypatch.setattr("app.workers.webhook_ingress.accept_answer_write_behind_many", capture_accept_many)
    worker = WebhookIngressWorker(
        bot=Bot(token="123:ABC", session=FakeTelegramSession()),
        dispatcher=_DispatcherSpy(),
        queue=queue,
        answer_queue=object(),
        config=WebhookIngressWorkerConfig(fast_answer_path=True, max_parallelism=1),
    )

    processed = await worker.process_once()

    assert processed == 2
    assert [request.session_id for request in requests] == [1, 2]
    assert queue.marked_update_ids == [[101, 102]]


@pytest.mark.asyncio
async def test_webhook_ingress_worker_retries_one_failed_message_without_blocking_batch() -> None:
    queue = _BatchQueueStub([_message(101), _message(102)])
    dispatcher = _SelectiveFailDispatcher(fail_update_id=101)
    worker = WebhookIngressWorker(
        bot=Bot(token="123:ABC", session=FakeTelegramSession()),
        dispatcher=dispatcher,
        queue=queue,
        config=WebhookIngressWorkerConfig(max_parallelism=2, max_attempts=3),
    )

    processed = await worker.process_once()

    assert processed == 2
    assert queue.retried_update_ids == [101]
    assert queue.marked_update_ids == [[102]]


@pytest.mark.asyncio
async def test_webhook_ingress_worker_sends_message_to_dlq_after_max_retries() -> None:
    message = _message(101, attempt=2)
    queue = _BatchQueueStub([message])
    worker = WebhookIngressWorker(
        bot=Bot(token="123:ABC", session=FakeTelegramSession()),
        dispatcher=_SelectiveFailDispatcher(fail_update_id=101),
        queue=queue,
        config=WebhookIngressWorkerConfig(max_parallelism=1, max_attempts=3),
    )

    processed = await worker.process_once()

    assert processed == 1
    assert queue.dead_update_ids == [101]
    assert queue.marked_update_ids == []


@pytest.mark.asyncio
async def test_webhook_ingress_worker_does_not_persist_answer_before_fast_ack(monkeypatch) -> None:
    queue = _BatchQueueStub([_callback_message(101, 1, "tok1")])
    answer_queue = object()

    async def accept_many(*, queue, requests: list[object]):
        assert queue is answer_queue
        return [_answer_result(request.session_id) for request in requests]

    async def fail_persistence(*_args, **_kwargs):
        raise AssertionError("fast ACK path must not call answer persistence directly")

    monkeypatch.setattr("app.workers.webhook_ingress.accept_answer_write_behind_many", accept_many)
    monkeypatch.setattr("app.workers.answer_persistence.persist_answer_events", fail_persistence)
    worker = WebhookIngressWorker(
        bot=Bot(token="123:ABC", session=FakeTelegramSession()),
        dispatcher=_DispatcherSpy(),
        queue=queue,
        answer_queue=answer_queue,
        config=WebhookIngressWorkerConfig(fast_answer_path=True, max_parallelism=1),
    )

    processed = await worker.process_once()

    assert processed == 1
    assert queue.marked_update_ids == [[101]]


@pytest.mark.asyncio
async def test_webhook_ingress_worker_retries_fast_answer_batch_failures(monkeypatch) -> None:
    queue = _BatchQueueStub([_callback_message(101, 1, "tok1"), _callback_message(102, 2, "tok2")])

    async def accept_many(*, queue, requests: list[object]):
        del queue, requests
        return [_answer_result(1), RuntimeError("duplicate callback state conflict")]

    monkeypatch.setattr("app.workers.webhook_ingress.accept_answer_write_behind_many", accept_many)
    worker = WebhookIngressWorker(
        bot=Bot(token="123:ABC", session=FakeTelegramSession()),
        dispatcher=_DispatcherSpy(),
        queue=queue,
        answer_queue=object(),
        config=WebhookIngressWorkerConfig(fast_answer_path=True, max_parallelism=1),
    )

    processed = await worker.process_once()

    assert processed == 2
    assert queue.marked_update_ids == [[101]]
    assert queue.retried_update_ids == [102]


def _message(update_id: int, *, attempt: int = 0) -> WebhookStreamMessage:
    return WebhookStreamMessage(
        message_id=f"{update_id}-0",
        update_id=update_id,
        payload={
            "update_id": update_id,
            "message": {
                "message_id": update_id,
                "date": 1_720_000_000,
                "chat": {"id": 1001, "type": "private"},
                "from": {"id": 1001, "is_bot": False, "first_name": "Ada"},
                "text": "/start",
            },
        },
        enqueued_at_ms=1,
        attempt=attempt,
    )


def _callback_message(update_id: int, session_id: int, question_token: str) -> WebhookStreamMessage:
    return WebhookStreamMessage(
        message_id=f"{update_id}-0",
        update_id=update_id,
        payload={
            "update_id": update_id,
            "callback_query": {
                "id": f"cbq-{update_id}",
                "from": {"id": 700001, "is_bot": False, "first_name": "Ada"},
                "data": f"train:ans:{session_id}:{question_token}:a1",
            },
        },
        enqueued_at_ms=1,
        attempt=0,
    )


def _answer_result(session_id: int) -> AnswerResult:
    return AnswerResult(
        selected_answer="a1",
        correct_answer="a2",
        question_token="tok",
        is_correct=False,
        is_duplicate=False,
        is_completed=False,
        explanation=None,
        correct_answers=0,
        total_questions=5,
        session_id=session_id,
    )


class _DispatcherSpy:
    def __init__(self) -> None:
        self.feed_webhook_update_called = False
        self.update: Update | None = None
        self.kwargs: dict[str, object] = {}

    async def feed_webhook_update(self, *args: object, **kwargs: object) -> None:
        del args, kwargs
        self.feed_webhook_update_called = True

    async def feed_update(self, bot: Bot, update: Update, **kwargs: object) -> None:
        del bot
        self.update = update
        self.kwargs = dict(kwargs)


class _QueueStub:
    async def retry_or_dead(self, *args: object, **kwargs: object) -> None:
        del args, kwargs


class _BatchQueueStub(_QueueStub):
    def __init__(self, messages: list[WebhookStreamMessage]) -> None:
        self._messages = messages
        self.marked_update_ids: list[list[int]] = []
        self.retried_update_ids: list[int] = []
        self.dead_update_ids: list[int] = []

    async def claim_stale(self, *args: object, **kwargs: object) -> list[WebhookStreamMessage]:
        del args, kwargs
        return []

    async def read_batch(self, *args: object, **kwargs: object) -> list[WebhookStreamMessage]:
        del args, kwargs
        messages = self._messages
        self._messages = []
        return messages

    async def mark_processed_many(
        self,
        messages: list[WebhookStreamMessage],
        *,
        dispatch_durations_ms: list[float] | None = None,
    ) -> None:
        assert dispatch_durations_ms is not None
        assert len(dispatch_durations_ms) == len(messages)
        self.marked_update_ids.append([message.update_id for message in messages])

    async def retry_or_dead(self, message, *, max_attempts: int, error_message: str) -> bool:
        del error_message
        if message.attempt + 1 >= max_attempts:
            self.dead_update_ids.append(message.update_id)
            return False
        self.retried_update_ids.append(message.update_id)
        return True


class _SelectiveFailDispatcher(_DispatcherSpy):
    def __init__(self, *, fail_update_id: int) -> None:
        super().__init__()
        self._fail_update_id = fail_update_id

    async def feed_update(self, bot: Bot, update: Update, **kwargs: object) -> None:
        if update.update_id == self._fail_update_id:
            raise RedisError("simulated dispatch dependency failure")
        await super().feed_update(bot, update, **kwargs)
