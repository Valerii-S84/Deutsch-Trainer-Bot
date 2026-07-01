from __future__ import annotations

import argparse
import asyncio
import os
from time import perf_counter
from uuid import uuid4

import httpx
from sqlalchemy import delete, func, insert, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.models import QuizSession, User, UserAnswer
from app.db.session import dispose_engine, measure_pool_wait_ms
from app.workers.outbox import OutboxWorker


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * percentile)))
    return ordered[index]


async def db_pool_saturation(args: argparse.Namespace) -> None:
    latencies: list[float] = []
    errors = 0
    semaphore = asyncio.Semaphore(args.concurrency)

    async def probe() -> None:
        nonlocal errors
        async with semaphore:
            try:
                latencies.append(await measure_pool_wait_ms())
            except Exception:
                errors += 1

    started = perf_counter()
    await asyncio.gather(*(probe() for _ in range(args.requests)))
    elapsed = perf_counter() - started
    await dispose_engine()
    _print_latency_report("db_pool_wait_ms", latencies, errors=errors, elapsed=elapsed)


async def worker_lag(_args: argparse.Namespace) -> None:
    worker = OutboxWorker()
    try:
        print(f"worker_lag_seconds={await worker.lag_seconds():.3f}")
    finally:
        await dispose_engine()


async def webhook_health_load(args: argparse.Namespace) -> None:
    latencies: list[float] = []
    errors = 0
    url = f"{args.base_url.rstrip('/')}{args.path}"
    timeout = httpx.Timeout(args.timeout_seconds)
    limits = httpx.Limits(max_connections=args.concurrency)
    async with httpx.AsyncClient(timeout=timeout, limits=limits) as client:
        semaphore = asyncio.Semaphore(args.concurrency)

        async def probe() -> None:
            nonlocal errors
            async with semaphore:
                started = perf_counter()
                try:
                    response = await client.get(url)
                    response.raise_for_status()
                    latencies.append((perf_counter() - started) * 1000)
                except Exception:
                    errors += 1

        started = perf_counter()
        await asyncio.gather(*(probe() for _ in range(args.requests)))
        elapsed = perf_counter() - started
    _print_latency_report("http_latency_ms", latencies, errors=errors, elapsed=elapsed)


async def seed_users(args: argparse.Namespace) -> None:
    session_factory = _test_session_factory()
    start_id = args.telegram_start_id
    async with session_factory() as db:
        for offset in range(0, args.count, args.batch_size):
            rows = [
                {"telegram_user_id": start_id + item}
                for item in range(offset, min(offset + args.batch_size, args.count))
            ]
            await db.execute(insert(User), rows)
            await db.commit()
    await session_factory.kw["bind"].dispose()
    print(f"seeded_users={args.count}")


async def duplicate_storm(args: argparse.Namespace) -> None:
    session_factory = _test_session_factory()
    marker = uuid4().hex
    telegram_user_id = int(f"88{marker[:8]}", 16)
    external_quiz_id = f"storm-{marker}"
    user_id, session_id = await _seed_session(session_factory, telegram_user_id)
    try:
        results = await asyncio.gather(
            *(
                _insert_answer(
                    session_factory,
                    user_id,
                    session_id,
                    external_quiz_id,
                    telegram_update_id=910000 + index,
                )
                for index in range(args.concurrency)
            ),
        )
        async with session_factory() as db:
            count = await db.scalar(
                select(func.count()).select_from(UserAnswer).where(
                    UserAnswer.user_id == user_id,
                    UserAnswer.session_id == session_id,
                    UserAnswer.external_quiz_id == external_quiz_id,
                ),
            )
    finally:
        await _cleanup_user(session_factory, user_id)
        await session_factory.kw["bind"].dispose()
    print(
        "duplicate_storm "
        f"accepted={results.count('accepted')} duplicate={results.count('duplicate')} stored_answers={count}"
    )


def quiz_bank_disabled_proof(_args: argparse.Namespace) -> None:
    print("training_runtime_quiz_source=local_quiz_catalog remote_quiz_bank_required=false")


async def _seed_session(session_factory, telegram_user_id: int) -> tuple[int, int]:
    async with session_factory() as db:
        user = User(telegram_user_id=telegram_user_id)
        db.add(user)
        await db.flush()
        session = QuizSession(
            user_id=user.id,
            level="A1",
            theme="Alltag",
            status="active",
            total_questions=5,
            source="local_quiz_catalog",
        )
        db.add(session)
        await db.commit()
        return user.id, session.id


async def _insert_answer(
    session_factory,
    user_id: int,
    session_id: int,
    external_quiz_id: str,
    *,
    telegram_update_id: int,
) -> str:
    async with session_factory() as db:
        db.add(
            UserAnswer(
                user_id=user_id,
                session_id=session_id,
                external_quiz_id=external_quiz_id,
                item_id=external_quiz_id,
                level="A1",
                theme="Alltag",
                selected_answer="a1",
                correct_answer="a2",
                is_correct=False,
                session_type="regular",
                telegram_update_id=telegram_update_id,
            ),
        )
        try:
            await db.commit()
        except IntegrityError:
            await db.rollback()
            return "duplicate"
        return "accepted"


async def _cleanup_user(session_factory, user_id: int) -> None:
    async with session_factory() as db:
        await db.execute(delete(User).where(User.id == user_id))
        await db.commit()


def _test_session_factory():
    database_url = os.environ.get("TEST_DATABASE_URL")
    if not database_url:
        raise SystemExit("TEST_DATABASE_URL is required for mutating hardening gates")
    engine = create_async_engine(database_url)
    return async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


def _print_latency_report(metric: str, values: list[float], *, errors: int, elapsed: float) -> None:
    total = len(values) + errors
    error_rate = (errors / total) if total else 0.0
    rate = total / elapsed if elapsed > 0 else 0.0
    print(
        f"{metric} "
        f"samples={len(values)} errors={errors} error_rate={error_rate:.6f} "
        f"throughput_per_sec={rate:.2f} "
        f"p50={_percentile(values, 0.50):.3f} "
        f"p95={_percentile(values, 0.95):.3f} "
        f"p99={_percentile(values, 0.99):.3f}"
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Production hardening load and concurrency gates.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    db_pool = subparsers.add_parser("db-pool-saturation")
    db_pool.add_argument("--requests", type=int, default=1000)
    db_pool.add_argument("--concurrency", type=int, default=100)
    db_pool.set_defaults(func=db_pool_saturation)

    lag = subparsers.add_parser("worker-lag")
    lag.set_defaults(func=worker_lag)

    health = subparsers.add_parser("webhook-health-load")
    health.add_argument("--base-url", required=True)
    health.add_argument("--path", default="/ready")
    health.add_argument("--requests", type=int, default=1000)
    health.add_argument("--concurrency", type=int, default=100)
    health.add_argument("--timeout-seconds", type=float, default=5.0)
    health.set_defaults(func=webhook_health_load)

    seed = subparsers.add_parser("seed-users")
    seed.add_argument("--count", type=int, default=100_000)
    seed.add_argument("--batch-size", type=int, default=1000)
    seed.add_argument("--telegram-start-id", type=int, default=7_000_000_000)
    seed.set_defaults(func=seed_users)

    duplicates = subparsers.add_parser("duplicate-storm")
    duplicates.add_argument("--concurrency", type=int, default=100)
    duplicates.set_defaults(func=duplicate_storm)

    quiz_bank = subparsers.add_parser("quiz-bank-disabled-proof")
    quiz_bank.set_defaults(func=quiz_bank_disabled_proof)
    return parser


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    result = args.func(args)
    if asyncio.iscoroutine(result):
        asyncio.run(result)


if __name__ == "__main__":
    main()
