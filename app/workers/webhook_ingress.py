from __future__ import annotations

import asyncio
from dataclasses import dataclass
import logging
from socket import gethostname
from time import perf_counter
from uuid import uuid4

from aiogram import Bot, Dispatcher
from aiogram.methods import TelegramMethod
from aiogram.types import Update

from app.bot.handlers.training_flow import parse_answer_payload
from app.bot.texts import CALLBACK_TRAIN_ANSWER_PREFIX
from app.runtime.answer_persistence_queue import AnswerPersistenceQueue
from app.runtime.webhook_ingress_queue import (
    WebhookIngressQueue,
    WebhookIngressQueueError,
    WebhookStreamMessage,
)
from app.services.training_answer_write_behind import (
    AnswerWriteBehindRequest,
    accept_answer_write_behind,
    accept_answer_write_behind_many,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class WebhookIngressWorkerConfig:
    consumer_name: str | None = None
    batch_size: int = 50
    max_parallelism: int = 20
    block_ms: int = 1000
    stale_idle_ms: int = 60_000
    max_attempts: int = 5
    fast_answer_path: bool = False


class WebhookIngressWorker:
    """Consume queued Telegram updates and process them through aiogram workers."""

    def __init__(
        self,
        *,
        bot: Bot,
        dispatcher: Dispatcher,
        queue: WebhookIngressQueue,
        answer_queue: AnswerPersistenceQueue | None = None,
        config: WebhookIngressWorkerConfig | None = None,
    ) -> None:
        config = config or WebhookIngressWorkerConfig()
        self._bot = bot
        self._dispatcher = dispatcher
        self._queue = queue
        self._answer_queue = answer_queue
        self._consumer_name = config.consumer_name or f"{gethostname()}:{uuid4().hex[:12]}"
        self._batch_size = max(1, config.batch_size)
        self._max_parallelism = max(1, config.max_parallelism)
        self._block_ms = max(1, config.block_ms)
        self._stale_idle_ms = max(1, config.stale_idle_ms)
        self._max_attempts = max(1, config.max_attempts)
        self._fast_answer_path = config.fast_answer_path

    async def process_once(self) -> int:
        messages = await self._queue.claim_stale(
            consumer_name=self._consumer_name,
            min_idle_ms=self._stale_idle_ms,
            count=self._batch_size,
        )
        if not messages:
            messages = await self._queue.read_batch(
                consumer_name=self._consumer_name,
                count=self._batch_size,
                block_ms=self._block_ms,
            )
        if not messages:
            return 0

        await self._process_messages(messages)
        return len(messages)

    async def run_forever(self, *, idle_sleep_seconds: float = 0.1) -> None:
        while True:
            try:
                processed = await self.process_once()
            except WebhookIngressQueueError:
                logger.exception("webhook ingress queue unavailable; retrying")
                await asyncio.sleep(max(1.0, idle_sleep_seconds))
                continue
            if processed == 0:
                await asyncio.sleep(max(0.0, idle_sleep_seconds))

    async def _process_messages(self, messages: list[WebhookStreamMessage]) -> None:
        if self._fast_answer_path and self._answer_queue is not None:
            completed, messages = await self._process_fast_answer_messages(messages)
            await self._mark_completed(completed)
            if not messages:
                return

        semaphore = asyncio.Semaphore(self._max_parallelism)

        async def _bounded(message: WebhookStreamMessage) -> tuple[WebhookStreamMessage, float] | None:
            async with semaphore:
                return await self._process_message(message)

        completed: list[tuple[WebhookStreamMessage, float]] = []
        for task in asyncio.as_completed([_bounded(message) for message in messages]):
            result = await task
            if result is None:
                continue
            completed.append(result)
            if len(completed) >= self._max_parallelism:
                await self._mark_completed(completed)
                completed.clear()
        await self._mark_completed(completed)

    async def _mark_completed(self, completed: list[tuple[WebhookStreamMessage, float]]) -> None:
        if not completed:
            return
        await self._queue.mark_processed_many(
            [message for message, _duration_ms in completed],
            dispatch_durations_ms=[duration_ms for _message, duration_ms in completed],
        )

    async def _process_message(self, message: WebhookStreamMessage) -> tuple[WebhookStreamMessage, float] | None:
        started = perf_counter()
        try:
            if await self._try_process_fast_answer(message):
                return message, (perf_counter() - started) * 1000
            update = Update.model_validate(message.payload, context={"bot": self._bot})
            result = await self._dispatcher.feed_update(
                self._bot,
                update,
                skip_backpressure=True,
                skip_duplicate_guard=True,
                skip_rate_limit=True,
            )
            if isinstance(result, TelegramMethod):
                await self._bot(result)
            return message, (perf_counter() - started) * 1000
        except Exception as exc:
            logger.exception(
                "webhook ingress message processing failed: message_id=%s update_id=%s attempt=%s",
                message.message_id,
                message.update_id,
                message.attempt,
            )
            await self._queue.retry_or_dead(
                message,
                max_attempts=self._max_attempts,
                error_message=f"{exc.__class__.__name__}: {exc}",
            )
            return None

    async def _process_fast_answer_messages(
        self,
        messages: list[WebhookStreamMessage],
    ) -> tuple[list[tuple[WebhookStreamMessage, float]], list[WebhookStreamMessage]]:
        started = perf_counter()
        batch: list[tuple[WebhookStreamMessage, AnswerWriteBehindRequest]] = []
        passthrough: list[WebhookStreamMessage] = []
        for message in messages:
            try:
                request = self._fast_answer_request(message)
            except Exception as exc:
                await self._retry_message(message, exc)
                continue
            if request is None:
                passthrough.append(message)
                continue
            batch.append((message, request))
        if not batch:
            return [], passthrough

        try:
            results = await accept_answer_write_behind_many(
                queue=self._answer_queue,
                requests=[request for _message, request in batch],
            )
        except Exception as exc:
            for message, _request in batch:
                await self._retry_message(message, exc)
            return [], passthrough

        duration_ms = (perf_counter() - started) * 1000
        completed: list[tuple[WebhookStreamMessage, float]] = []
        for (message, _request), result in zip(batch, results):
            if isinstance(result, Exception):
                await self._retry_message(message, result)
                continue
            completed.append((message, duration_ms))
        return completed, passthrough

    async def _retry_message(self, message: WebhookStreamMessage, exc: Exception) -> None:
        logger.exception(
            "webhook ingress message processing failed: message_id=%s update_id=%s attempt=%s",
            message.message_id,
            message.update_id,
            message.attempt,
            exc_info=(type(exc), exc, exc.__traceback__),
        )
        await self._queue.retry_or_dead(
            message,
            max_attempts=self._max_attempts,
            error_message=f"{exc.__class__.__name__}: {exc}",
        )

    async def _try_process_fast_answer(self, message: WebhookStreamMessage) -> bool:
        if not self._fast_answer_path or self._answer_queue is None:
            return False
        request = self._fast_answer_request(message)
        if request is None:
            return False
        await accept_answer_write_behind(
            queue=self._answer_queue,
            telegram_user_id=request.telegram_user_id,
            session_id=request.session_id,
            question_token=request.question_token,
            selected_option_id=request.selected_option_id,
            telegram_update_id=request.telegram_update_id,
            callback_query_id=request.callback_query_id,
        )
        return True

    def _fast_answer_request(self, message: WebhookStreamMessage) -> AnswerWriteBehindRequest | None:
        callback_query = message.payload.get("callback_query")
        if not isinstance(callback_query, dict):
            return None
        callback_data = callback_query.get("data")
        if not isinstance(callback_data, str) or not callback_data.startswith(
            CALLBACK_TRAIN_ANSWER_PREFIX + ":"
        ):
            return None
        from_user = callback_query.get("from")
        if not isinstance(from_user, dict):
            raise ValueError("callback query is missing from user")
        telegram_user_id = from_user.get("id")
        if isinstance(telegram_user_id, bool) or not isinstance(telegram_user_id, int):
            raise ValueError("callback query user id must be an integer")
        callback_query_id = callback_query.get("id")
        session_id, question_token, selected_option_id = parse_answer_payload(callback_data)
        return AnswerWriteBehindRequest(
            telegram_user_id=telegram_user_id,
            session_id=session_id,
            question_token=question_token,
            selected_option_id=selected_option_id,
            telegram_update_id=message.update_id,
            callback_query_id=callback_query_id if isinstance(callback_query_id, str) else None,
        )
