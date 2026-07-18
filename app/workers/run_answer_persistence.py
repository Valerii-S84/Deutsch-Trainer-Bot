from __future__ import annotations

import argparse
import asyncio

from app.config import get_settings
from app.db.session import dispose_engine
from app.logging_config import configure_logging
from app.runtime.answer_persistence_queue import create_answer_persistence_queue
from app.runtime.redis import close_redis_client, create_redis_client, warm_redis_client
from app.workers.answer_persistence import AnswerPersistenceWorker


async def _run(args: argparse.Namespace) -> None:
    settings = get_settings()
    configure_logging(settings.log_level)

    redis_client = create_redis_client(settings)
    if settings.redis_warmup_connections > 0:
        await warm_redis_client(
            redis_client,
            connection_count=min(settings.redis_warmup_connections, settings.redis_max_connections),
        )
    queue = create_answer_persistence_queue(settings, redis_client)
    await queue.warm()
    worker = AnswerPersistenceWorker(
        queue=queue,
        batch_size=args.batch_size,
        flush_interval_ms=args.flush_interval_ms,
        stale_idle_ms=args.stale_idle_ms,
        max_attempts=args.max_attempts,
    )
    try:
        if args.once:
            persisted = await worker.process_once()
            stats = await queue.stats()
            print(
                "persisted="
                f"{persisted} queue_depth={stats.queue_depth} "
                f"oldest_lag_ms={stats.oldest_lag_ms} dead={stats.dead_letter_length}"
            )
            return
        await worker.run_forever(idle_sleep_seconds=args.idle_sleep_seconds)
    finally:
        await close_redis_client(redis_client)
        await dispose_engine()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the answer persistence queue worker.")
    parser.add_argument("--once", action="store_true", help="Process one batch and exit.")
    parser.add_argument("--batch-size", type=int, default=None)
    parser.add_argument("--flush-interval-ms", type=int, default=None)
    parser.add_argument("--stale-idle-ms", type=int, default=None)
    parser.add_argument("--max-attempts", type=int, default=None)
    parser.add_argument("--idle-sleep-seconds", type=float, default=0.02)
    args = parser.parse_args()

    settings = get_settings()
    args.batch_size = args.batch_size or settings.answer_persist_batch_size
    args.flush_interval_ms = args.flush_interval_ms or settings.answer_persist_flush_interval_ms
    args.stale_idle_ms = args.stale_idle_ms or settings.answer_persist_stale_idle_ms
    args.max_attempts = args.max_attempts or settings.answer_persist_max_attempts
    asyncio.run(_run(args))


if __name__ == "__main__":
    main()
