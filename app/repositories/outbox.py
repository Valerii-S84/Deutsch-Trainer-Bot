from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import OutboxEvent
from app.repositories.sqlite_compat import next_sqlite_id_if_needed


OUTBOX_PENDING = "pending"
OUTBOX_PROCESSING = "processing"
OUTBOX_DONE = "done"
OUTBOX_FAILED = "failed"
OUTBOX_DEAD = "dead"


class OutboxRepository:
    """Persistence helpers for durable outbox processing."""

    async def enqueue(
        self,
        db: AsyncSession,
        *,
        event_type: str,
        aggregate_type: str,
        aggregate_id: int | None,
        idempotency_key: str,
        payload: dict[str, object],
    ) -> OutboxEvent:
        if _dialect_name(db) == "postgresql":
            statement = (
                postgresql_insert(OutboxEvent)
                .values(
                    event_type=event_type,
                    aggregate_type=aggregate_type,
                    aggregate_id=aggregate_id,
                    idempotency_key=idempotency_key,
                    payload=payload,
                )
                .on_conflict_do_nothing(index_elements=[OutboxEvent.idempotency_key])
                .returning(OutboxEvent.id)
            )
            event_id = await db.scalar(statement)
            if event_id is not None:
                return OutboxEvent(
                    id=int(event_id),
                    event_type=event_type,
                    aggregate_type=aggregate_type,
                    aggregate_id=aggregate_id,
                    idempotency_key=idempotency_key,
                    payload=payload,
                )
            existing = await self.get_by_idempotency_key(db, idempotency_key)
            if existing is None:
                raise RuntimeError("Outbox insert conflicted but existing event was not found")
            return existing

        existing = await self.get_by_idempotency_key(db, idempotency_key)
        if existing is not None:
            return existing

        event_id = await next_sqlite_id_if_needed(db, OutboxEvent)
        event = OutboxEvent(
            id=event_id,
            event_type=event_type,
            aggregate_type=aggregate_type,
            aggregate_id=aggregate_id,
            idempotency_key=idempotency_key,
            payload=payload,
        )
        db.add(event)
        await db.flush()
        return event

    async def get_by_idempotency_key(self, db: AsyncSession, idempotency_key: str) -> OutboxEvent | None:
        return await db.scalar(select(OutboxEvent).where(OutboxEvent.idempotency_key == idempotency_key))

    async def claim_batch(
        self,
        db: AsyncSession,
        *,
        worker_id: str,
        batch_size: int,
        now: datetime | None = None,
    ) -> list[OutboxEvent]:
        claim_time = now or datetime.now(UTC)
        if _dialect_name(db) == "postgresql":
            return await _claim_batch_postgresql(
                db,
                worker_id=worker_id,
                batch_size=batch_size,
                claim_time=claim_time,
            )

        query = (
            select(OutboxEvent)
            .where(
                and_(
                    OutboxEvent.status.in_((OUTBOX_PENDING, OUTBOX_FAILED)),
                    OutboxEvent.next_attempt_at <= claim_time,
                    OutboxEvent.retry_count < OutboxEvent.max_retries,
                ),
            )
            .order_by(
                OutboxEvent.next_attempt_at.asc(),
                OutboxEvent.created_at.asc(),
                OutboxEvent.id.asc(),
            )
            .limit(batch_size)
        )
        events = list((await db.scalars(query)).all())
        for event in events:
            event.status = OUTBOX_PROCESSING
            event.locked_at = claim_time
            event.locked_by = worker_id
        if events:
            await db.flush()
        return events

    async def mark_done(self, db: AsyncSession, event: OutboxEvent, *, now: datetime | None = None) -> OutboxEvent:
        completed_at = now or datetime.now(UTC)
        event.status = OUTBOX_DONE
        event.processed_at = completed_at
        event.failed_at = None
        event.dead_at = None
        event.locked_at = None
        event.locked_by = None
        event.last_error = None
        await db.flush()
        return event

    async def mark_done_by_id(
        self,
        db: AsyncSession,
        event_id: int,
        *,
        now: datetime | None = None,
    ) -> None:
        completed_at = now or datetime.now(UTC)
        if _dialect_name(db) == "postgresql":
            await db.execute(
                update(OutboxEvent)
                .where(OutboxEvent.id == event_id)
                .values(
                    status=OUTBOX_DONE,
                    processed_at=completed_at,
                    failed_at=None,
                    dead_at=None,
                    locked_at=None,
                    locked_by=None,
                    last_error=None,
                ),
            )
            return

        event = await db.get(OutboxEvent, event_id)
        if event is None:
            return
        await self.mark_done(db, event, now=completed_at)

    async def mark_failed(
        self,
        db: AsyncSession,
        event: OutboxEvent,
        *,
        error_message: str,
        now: datetime | None = None,
    ) -> OutboxEvent:
        failed_at = now or datetime.now(UTC)
        event.retry_count = int(event.retry_count or 0) + 1
        event.last_error = error_message[:1000]
        event.locked_at = None
        event.locked_by = None
        if event.retry_count >= int(event.max_retries or 0):
            event.status = OUTBOX_DEAD
            event.dead_at = failed_at
            event.failed_at = failed_at
        else:
            event.status = OUTBOX_FAILED
            event.failed_at = failed_at
            event.next_attempt_at = failed_at + timedelta(seconds=_retry_delay_seconds(event.retry_count))
        await db.flush()
        return event

    async def mark_failed_by_id(
        self,
        db: AsyncSession,
        event_id: int,
        *,
        error_message: str,
        now: datetime | None = None,
    ) -> None:
        failed_at = now or datetime.now(UTC)
        if _dialect_name(db) == "postgresql":
            event = await db.get(OutboxEvent, event_id)
            if event is None:
                return
            await self.mark_failed(db, event, error_message=error_message, now=failed_at)
            return

        event = await db.get(OutboxEvent, event_id)
        if event is None:
            return
        await self.mark_failed(db, event, error_message=error_message, now=failed_at)

    async def requeue_stale_processing(
        self,
        db: AsyncSession,
        *,
        stale_after_seconds: int,
        now: datetime | None = None,
    ) -> int:
        current_time = now or datetime.now(UTC)
        stale_before = current_time - timedelta(seconds=max(1, stale_after_seconds))
        if _dialect_name(db) == "postgresql":
            rows = await db.execute(
                update(OutboxEvent)
                .where(
                    and_(
                        OutboxEvent.status == OUTBOX_PROCESSING,
                        or_(OutboxEvent.locked_at.is_(None), OutboxEvent.locked_at <= stale_before),
                    ),
                )
                .values(
                    status=OUTBOX_FAILED,
                    locked_at=None,
                    locked_by=None,
                    failed_at=current_time,
                    next_attempt_at=current_time,
                )
                .returning(OutboxEvent.id),
            )
            return len(rows.all())

        query = select(OutboxEvent).where(
            and_(
                OutboxEvent.status == OUTBOX_PROCESSING,
                or_(OutboxEvent.locked_at.is_(None), OutboxEvent.locked_at <= stale_before),
            ),
        )
        events = list((await db.scalars(query)).all())
        for event in events:
            event.status = OUTBOX_FAILED
            event.locked_at = None
            event.locked_by = None
            event.failed_at = current_time
            event.next_attempt_at = current_time
        if events:
            await db.flush()
        return len(events)

    async def pending_lag_seconds(self, db: AsyncSession, *, now: datetime | None = None) -> float:
        current_time = now or datetime.now(UTC)
        oldest = await db.scalar(
            select(func.min(OutboxEvent.created_at)).where(
                OutboxEvent.status.in_((OUTBOX_PENDING, OUTBOX_FAILED, OUTBOX_PROCESSING)),
            ),
        )
        if oldest is None:
            return 0.0
        if oldest.tzinfo is None:
            oldest = oldest.replace(tzinfo=UTC)
        return max(0.0, (current_time - oldest).total_seconds())


def _retry_delay_seconds(retry_count: int) -> int:
    return min(300, 2 ** max(0, retry_count - 1))


def _outbox_event_from_mapping(row: dict[str, object]) -> OutboxEvent:
    return OutboxEvent(
        id=int(row["id"]),
        event_type=str(row["event_type"]),
        aggregate_type=str(row["aggregate_type"]),
        aggregate_id=int(row["aggregate_id"]) if row["aggregate_id"] is not None else None,
        idempotency_key=str(row["idempotency_key"]),
        status=str(row["status"]),
        payload=dict(row["payload"]),
        retry_count=int(row["retry_count"]),
        max_retries=int(row["max_retries"]),
        next_attempt_at=row["next_attempt_at"],
        locked_at=row["locked_at"],
        locked_by=row["locked_by"],
        processed_at=row["processed_at"],
        failed_at=row["failed_at"],
        dead_at=row["dead_at"],
        last_error=row["last_error"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


async def _claim_batch_postgresql(
    db: AsyncSession,
    *,
    worker_id: str,
    batch_size: int,
    claim_time: datetime,
) -> list[OutboxEvent]:
    claimable = (
        select(OutboxEvent.id)
        .where(
            and_(
                OutboxEvent.status.in_((OUTBOX_PENDING, OUTBOX_FAILED)),
                OutboxEvent.next_attempt_at <= claim_time,
                OutboxEvent.retry_count < OutboxEvent.max_retries,
            ),
        )
        .order_by(
            OutboxEvent.next_attempt_at.asc(),
            OutboxEvent.created_at.asc(),
            OutboxEvent.id.asc(),
        )
        .limit(batch_size)
        .with_for_update(skip_locked=True)
        .cte("claimable_outbox_events")
    )
    statement = (
        update(OutboxEvent)
        .where(OutboxEvent.id.in_(select(claimable.c.id)))
        .values(
            status=OUTBOX_PROCESSING,
            locked_at=claim_time,
            locked_by=worker_id,
        )
        .returning(*OutboxEvent.__table__.c)
    )
    rows = (await db.execute(statement)).mappings().all()
    return [_outbox_event_from_mapping(dict(row)) for row in rows]


def _dialect_name(db: AsyncSession) -> str:
    bind = db.get_bind()
    return bind.dialect.name if bind is not None else ""
