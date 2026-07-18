from __future__ import annotations

import argparse
import asyncio

from app.bot.dispatcher import build_dispatcher
from app.config import get_settings
from app.db.session import dispose_engine
from app.logging_config import configure_logging
from app.main import create_bot, create_webhook_ingress_queue
from app.runtime.answer_persistence_queue import AnswerPersistenceQueue, create_answer_persistence_queue
from app.runtime.redis import close_redis_client, create_redis_client, warm_redis_client
from app.workers.answer_persistence import AnswerPersistenceWorker
from app.workers.outbox import OutboxWorker
from app.workers.webhook_ingress import WebhookIngressWorker, WebhookIngressWorkerConfig


async def _run(args: argparse.Namespace) -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    if not settings.bot_token:
        raise RuntimeError("BOT_TOKEN must be set for webhook ingress worker")

    redis_client = create_redis_client(settings)
    if settings.redis_warmup_connections > 0:
        await warm_redis_client(
            redis_client,
            connection_count=min(settings.redis_warmup_connections, settings.redis_max_connections),
        )
    bot = create_bot(settings.bot_token.get_secret_value())
    dispatcher = build_dispatcher(settings, redis_client=redis_client)
    queue = create_webhook_ingress_queue(settings, redis_client)
    await queue.warm()
    answer_queue = _create_answer_queue(args, settings, redis_client)
    if answer_queue is not None:
        await answer_queue.warm()
    worker = _create_webhook_worker(args, bot=bot, dispatcher=dispatcher, queue=queue, answer_queue=answer_queue)
    try:
        if args.initial_delay_seconds > 0:
            await asyncio.sleep(args.initial_delay_seconds)
        if args.once:
            await _run_once(args, worker=worker, queue=queue, answer_queue=answer_queue)
            return
        await _run_forever_tasks(args, worker=worker, answer_queue=answer_queue)
    finally:
        await bot.session.close()
        await close_redis_client(redis_client)
        await dispose_engine()


def _create_answer_queue(args: argparse.Namespace, settings, redis_client) -> AnswerPersistenceQueue | None:
    fast_answer_path = bool(args.fast_answer_path)
    run_answer_persistence = settings.training_answer_write_behind_enabled and not args.without_answer_persistence
    if not settings.training_answer_write_behind_enabled:
        return None
    if run_answer_persistence or fast_answer_path:
        return create_answer_persistence_queue(settings, redis_client)
    return None


def _create_webhook_worker(
    args: argparse.Namespace,
    *,
    bot,
    dispatcher,
    queue,
    answer_queue: AnswerPersistenceQueue | None,
) -> WebhookIngressWorker:
    return WebhookIngressWorker(
        bot=bot,
        dispatcher=dispatcher,
        queue=queue,
        answer_queue=answer_queue,
        config=WebhookIngressWorkerConfig(
            batch_size=args.batch_size,
            max_parallelism=args.parallelism,
            block_ms=args.block_ms,
            stale_idle_ms=args.stale_idle_ms,
            max_attempts=args.max_attempts,
            fast_answer_path=bool(args.fast_answer_path),
        ),
    )


async def _run_once(
    args: argparse.Namespace,
    *,
    worker: WebhookIngressWorker,
    queue,
    answer_queue: AnswerPersistenceQueue | None,
) -> None:
    processed = await worker.process_once()
    persisted = 0
    if answer_queue is not None:
        persisted = await _create_answer_persistence_worker(args, answer_queue).process_once()
    if args.with_outbox_worker:
        await _create_outbox_worker(args).process_once()
    await _print_once_summary(processed, persisted, queue=queue, answer_queue=answer_queue)


async def _print_once_summary(processed: int, persisted: int, *, queue, answer_queue: AnswerPersistenceQueue | None) -> None:
    stats = await queue.stats()
    answer_stats = await answer_queue.stats() if answer_queue is not None else None
    print(
        "processed="
        f"{processed} queue_depth={stats.queue_depth} "
        f"oldest_lag_ms={stats.oldest_lag_ms} dead={stats.dead_letter_length} "
        f"answer_persisted={persisted} "
        f"answer_queue_depth={0 if answer_stats is None else answer_stats.queue_depth} "
        f"answer_dead={0 if answer_stats is None else answer_stats.dead_letter_length}"
    )


async def _run_forever_tasks(
    args: argparse.Namespace,
    *,
    worker: WebhookIngressWorker,
    answer_queue: AnswerPersistenceQueue | None,
) -> None:
    tasks = [worker.run_forever(idle_sleep_seconds=args.idle_sleep_seconds)]
    if answer_queue is not None:
        tasks.append(
            _create_answer_persistence_worker(args, answer_queue).run_forever(
                idle_sleep_seconds=args.answer_persist_idle_sleep_seconds,
            ),
        )
    if args.with_outbox_worker:
        tasks.append(_create_outbox_worker(args).run_forever(idle_sleep_seconds=args.outbox_idle_sleep_seconds))
    await asyncio.gather(*tasks)


def _create_outbox_worker(args: argparse.Namespace) -> OutboxWorker:
    return OutboxWorker(
        batch_size=args.outbox_batch_size,
        max_parallelism=args.outbox_parallelism,
        stale_after_seconds=args.outbox_stale_after_seconds,
    )


def _create_answer_persistence_worker(
    args: argparse.Namespace,
    answer_queue,
) -> AnswerPersistenceWorker:
    return AnswerPersistenceWorker(
        queue=answer_queue,
        batch_size=args.answer_persist_batch_size,
        flush_interval_ms=args.answer_persist_flush_interval_ms,
        stale_idle_ms=args.answer_persist_stale_idle_ms,
        max_attempts=args.answer_persist_max_attempts,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Telegram webhook ingress queue worker.")
    parser.add_argument("--once", action="store_true", help="Process one batch and exit.")
    parser.add_argument("--batch-size", type=int, default=None)
    parser.add_argument("--parallelism", type=int, default=None)
    parser.add_argument("--block-ms", type=int, default=None)
    parser.add_argument("--stale-idle-ms", type=int, default=None)
    parser.add_argument("--max-attempts", type=int, default=None)
    parser.add_argument("--idle-sleep-seconds", type=float, default=0.1)
    parser.add_argument("--initial-delay-seconds", type=float, default=0.0)
    parser.add_argument(
        "--without-answer-persistence",
        action="store_true",
        help="Run only the webhook dispatch consumer; answer persistence is handled by a separate pool.",
    )
    parser.add_argument(
        "--fast-answer-path",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Process training answer callbacks directly into the answer persistence queue.",
    )
    parser.add_argument(
        "--with-outbox-worker",
        action="store_true",
        help="Run the durable answer side-effect outbox worker in the same process.",
    )
    parser.add_argument("--outbox-batch-size", type=int, default=200)
    parser.add_argument("--outbox-parallelism", type=int, default=5)
    parser.add_argument("--outbox-stale-after-seconds", type=int, default=300)
    parser.add_argument("--outbox-idle-sleep-seconds", type=float, default=1.0)
    parser.add_argument("--answer-persist-batch-size", type=int, default=None)
    parser.add_argument("--answer-persist-flush-interval-ms", type=int, default=None)
    parser.add_argument("--answer-persist-stale-idle-ms", type=int, default=None)
    parser.add_argument("--answer-persist-max-attempts", type=int, default=None)
    parser.add_argument("--answer-persist-idle-sleep-seconds", type=float, default=0.02)
    args = parser.parse_args()

    settings = get_settings()
    args.batch_size = args.batch_size or settings.webhook_ingress_worker_batch_size
    args.parallelism = args.parallelism or settings.webhook_ingress_worker_parallelism
    args.block_ms = args.block_ms or settings.webhook_ingress_read_block_ms
    args.stale_idle_ms = args.stale_idle_ms or settings.webhook_ingress_stale_idle_ms
    args.max_attempts = args.max_attempts or settings.webhook_ingress_max_attempts
    args.fast_answer_path = (
        settings.webhook_ingress_fast_answer_path
        if args.fast_answer_path is None
        else args.fast_answer_path
    )
    args.answer_persist_batch_size = args.answer_persist_batch_size or settings.answer_persist_batch_size
    args.answer_persist_flush_interval_ms = (
        args.answer_persist_flush_interval_ms or settings.answer_persist_flush_interval_ms
    )
    args.answer_persist_stale_idle_ms = args.answer_persist_stale_idle_ms or settings.answer_persist_stale_idle_ms
    args.answer_persist_max_attempts = args.answer_persist_max_attempts or settings.answer_persist_max_attempts
    asyncio.run(_run(args))


if __name__ == "__main__":
    main()
