from __future__ import annotations

import argparse
import asyncio
import logging

from app.config import get_settings
from app.db.session import dispose_engine
from app.logging_config import configure_logging
from app.workers.outbox import OutboxWorker


async def _run(args: argparse.Namespace) -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    worker = OutboxWorker(batch_size=args.batch_size, stale_after_seconds=args.stale_after_seconds)
    try:
        if args.once:
            processed = await worker.process_once()
            lag_seconds = await worker.lag_seconds()
            print(f"processed={processed} worker_lag_seconds={lag_seconds:.3f}")
            return
        await worker.run_forever(idle_sleep_seconds=args.idle_sleep_seconds)
    finally:
        await dispose_engine()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Deutsch Trainer Bot outbox worker.")
    parser.add_argument("--once", action="store_true", help="Process one batch and exit.")
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument("--stale-after-seconds", type=int, default=300)
    parser.add_argument("--idle-sleep-seconds", type=float, default=1.0)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    asyncio.run(_run(args))


if __name__ == "__main__":
    main()
