from __future__ import annotations



from scripts import load_stabilization_orchestrator as _root
globals().update({name: value for name, value in vars(_root).items() if not name.startswith("__")})


async def _sample_postgres_lock_profile_until(
    stop_event: asyncio.Event,
    *,
    output_path: str,
    interval_ms: float,
    query_timeout_seconds: float,
) -> dict[str, Any]:
    interval_seconds = max(interval_ms, 100.0) / 1000.0
    samples: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    started_at = perf_counter()
    connection: asyncpg.Connection | None = None

    while not stop_event.is_set():
        sample_started = perf_counter()
        try:
            connection = await _postgres_sampler_connection(connection, query_timeout_seconds)
            samples.append(await _postgres_lock_sample(
                connection,
                offset_ms=round((sample_started - started_at) * 1000, 3),
                timeout_seconds=query_timeout_seconds,
            ))
        except Exception as exc:  # noqa: BLE001
            errors.append(
                {
                    "offset_ms": str(round((perf_counter() - started_at) * 1000, 3)),
                    "error": f"{exc.__class__.__name__}: {exc}",
                }
            )
            if connection is not None and not connection.is_closed():
                await connection.close()
            connection = None
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval_seconds)
        except asyncio.TimeoutError:
            continue

    if connection is not None and not connection.is_closed():
        await connection.close()

    payload = {
        "generated_at_utc": now_utc(),
        "sample_interval_ms": interval_ms,
        "sample_count": len(samples),
        "samples": samples,
        "summary": _summarize_postgres_lock_samples(samples, errors=errors),
        "errors": errors,
    }
    write_json(resolve_evidence_path(output_path), payload)
    return {**payload["summary"], "output_path": output_path}


async def _postgres_sampler_connection(
    connection: asyncpg.Connection | None, timeout_seconds: float,
) -> asyncpg.Connection:
    if connection is not None and not connection.is_closed():
        return connection
    return await asyncio.wait_for(_connect_postgres_lock_sampler(), timeout=timeout_seconds)


async def _postgres_lock_sample(
    connection: asyncpg.Connection, *, offset_ms: float, timeout_seconds: float,
) -> dict[str, Any]:
    queries = {
        "activity": POSTGRES_ACTIVITY_SQL,
        "waiting_activity": POSTGRES_WAITING_ACTIVITY_SQL,
        "lock_summary": POSTGRES_LOCK_SUMMARY_SQL,
        "lock_waits": POSTGRES_LOCK_WAITS_SQL,
        "blocking_chains": POSTGRES_BLOCKING_CHAINS_SQL,
    }
    sample: dict[str, Any] = {"offset_ms": offset_ms}
    for key, sql in queries.items():
        sample[key] = await _fetch_rows_with_timeout(
            connection, sql, timeout_seconds=timeout_seconds,
        )
    return sample


async def _connect_postgres_lock_sampler() -> asyncpg.Connection:
    dsn = _required_env("POSTGRES_LOCK_SAMPLE_DATABASE_URL")
    return await asyncpg.connect(
        _normalize_asyncpg_dsn(dsn),
        server_settings={"application_name": "dtb_lock_sampler"},
    )


def _normalize_asyncpg_dsn(dsn: str) -> str:
    return dsn.replace("postgresql+asyncpg://", "postgresql://", 1)


async def _validate_webhook_processing(args: argparse.Namespace) -> dict[str, Any]:
    database_url = os.environ.get("TEST_DATABASE_URL") or os.environ.get("DATABASE_URL")
    redis_url = os.environ.get("REDIS_URL")
    if not database_url:
        return {
            "passed": False,
            "error": "TEST_DATABASE_URL or DATABASE_URL is required for event validation",
        }
    if not redis_url:
        return {"passed": False, "error": "REDIS_URL is required for event validation"}

    start_update_id = args.start_update_id
    end_update_id = args.start_update_id + args.total_requests - 1
    connection: asyncpg.Connection | None = None
    redis_client: Redis | None = None
    started = perf_counter()
    deadline = started + args.queue_drain_timeout_seconds
    last: dict[str, Any] = {}

    try:
        connection = await asyncpg.connect(
            _normalize_asyncpg_dsn(database_url),
            server_settings={"application_name": "dtb_webhook_validation"},
        )
        redis_client = Redis.from_url(redis_url, decode_responses=True)
        while True:
            db_summary = await _fetch_webhook_db_validation(
                connection,
                start_update_id=start_update_id,
                end_update_id=end_update_id,
                expected_count=args.total_requests,
            )
            queue_processing = await _fetch_validation_queues(redis_client, args)
            passed = _webhook_validation_passed(db_summary, queue_processing, args)
            last = {
                "passed": passed,
                "expected_count": args.total_requests,
                "update_id_range": {"start": start_update_id, "end": end_update_id},
                "duration_seconds": round(perf_counter() - started, 3),
                "queue_processing": queue_processing,
                **db_summary,
            }
            if passed:
                return last
            if perf_counter() >= deadline:
                last["timeout_seconds"] = args.queue_drain_timeout_seconds
                return last
            await asyncio.sleep(args.queue_drain_poll_interval_seconds)
    except (asyncpg.PostgresError, RedisError) as exc:
        return {
            "passed": False,
            "error": f"{exc.__class__.__name__}: {exc}",
            "duration_seconds": round(perf_counter() - started, 3),
            **last,
        }
    finally:
        if connection is not None and not connection.is_closed():
            await connection.close()
        if redis_client is not None:
            await redis_client.aclose()


async def _fetch_validation_queues(
    redis_client: Redis, args: argparse.Namespace,
) -> dict[str, Any]:
    ingress = await _fetch_webhook_queue_validation(
        redis_client,
        stream_key=args.webhook_ingress_stream_key,
        dead_letter_key=args.webhook_ingress_dead_letter_key,
        metrics_key_prefix=args.webhook_ingress_metrics_key_prefix,
    )
    answers = await _fetch_webhook_queue_validation(
        redis_client,
        stream_key=args.answer_persist_stream_key,
        dead_letter_key=args.answer_persist_dead_letter_key,
        metrics_key_prefix=args.answer_persist_metrics_key_prefix,
    )
    return {
        "drained": _queue_drained(ingress) and _queue_drained(answers),
        "lag_ms": ingress.pop("processing_lag_ms"),
        "answer_persistence_lag_ms": answers.pop("processing_lag_ms"),
        "dead_letter_total": ingress["dead_letter_length"] + answers["dead_letter_length"],
        "answer_persistence": answers,
        **ingress,
    }


def _webhook_validation_passed(
    db: Mapping[str, Any], queue: Mapping[str, Any], args: argparse.Namespace,
) -> bool:
    outbox = db["outbox_for_answers"]
    return (
        db["persisted_count"] == args.total_requests
        and db["lost_count"] == 0
        and db["duplicate_update_count"] == 0
        and db["duplicate_quiz_answer_count"] == 0
        and outbox["missing"] == 0
        and outbox["bad_status_count"] == 0
        and queue["drained"]
        and queue["dead_letter_total"] == 0
        and queue["lag_ms"]["count"] >= args.total_requests
        and queue["lag_ms"]["p95"] <= args.max_processing_lag_p95_ms
    )


def _queue_drained(summary: Mapping[str, Any]) -> bool:
    return (
        int(summary.get("stream_length") or 0) == 0
        and int(summary.get("pending") or 0) == 0
        and int(summary.get("dead_letter_length") or 0) == 0
    )


async def _fetch_webhook_db_validation(
    connection: asyncpg.Connection,
    *,
    start_update_id: int,
    end_update_id: int,
    expected_count: int,
) -> dict[str, Any]:
    persisted_count, lost_rows = await _fetch_persisted_webhook_answers(
        connection, start_update_id, end_update_id,
    )
    duplicate_update_rows, duplicate_quiz_rows = await _fetch_duplicate_webhook_answers(
        connection, start_update_id, end_update_id,
    )
    outbox_rows = await _fetch_webhook_answer_outbox(connection, start_update_id, end_update_id)
    outbox_status_counts = {str(row["status"]): int(row["count"]) for row in outbox_rows}
    missing_outbox = outbox_status_counts.get("missing", 0)
    bad_outbox = sum(count for status, count in outbox_status_counts.items() if status not in {"done", "missing"})
    return {
        "persisted_count": persisted_count,
        "lost_count": max(0, expected_count - persisted_count),
        "lost_update_id_sample": [int(row["update_id"]) for row in lost_rows],
        "duplicate_update_count": sum(int(row["count"]) - 1 for row in duplicate_update_rows),
        "duplicate_update_id_sample": [dict(row) for row in duplicate_update_rows],
        "duplicate_quiz_answer_count": sum(int(row["count"]) - 1 for row in duplicate_quiz_rows),
        "duplicate_quiz_answer_sample": [dict(row) for row in duplicate_quiz_rows],
        "outbox_for_answers": {
            "status_counts": outbox_status_counts, "missing": missing_outbox, "bad_status_count": bad_outbox,
        },
    }


async def _fetch_persisted_webhook_answers(
    connection: asyncpg.Connection, start_update_id: int, end_update_id: int,
) -> tuple[int, list[asyncpg.Record]]:
    persisted_count = int(await connection.fetchval(
            """
            SELECT COUNT(*)::int
            FROM user_answers
            WHERE telegram_update_id BETWEEN $1 AND $2
            """,
            start_update_id,
            end_update_id,
        ) or 0)
    lost_rows = await connection.fetch(
        """
        SELECT expected.update_id::bigint AS update_id
        FROM generate_series($1::bigint, $2::bigint) AS expected(update_id)
        LEFT JOIN user_answers AS answer
          ON answer.telegram_update_id = expected.update_id
        WHERE answer.id IS NULL
        ORDER BY expected.update_id
        LIMIT 50
        """,
        start_update_id,
        end_update_id,
    )
    return persisted_count, lost_rows


async def _fetch_duplicate_webhook_answers(
    connection: asyncpg.Connection, start_update_id: int, end_update_id: int,
) -> tuple[list[asyncpg.Record], list[asyncpg.Record]]:
    duplicate_update_rows = await connection.fetch(
        """
        SELECT telegram_update_id::bigint AS telegram_update_id, COUNT(*)::int AS count
        FROM user_answers
        WHERE telegram_update_id BETWEEN $1 AND $2
        GROUP BY telegram_update_id
        HAVING COUNT(*) > 1
        ORDER BY telegram_update_id
        LIMIT 50
        """,
        start_update_id,
        end_update_id,
    )
    duplicate_quiz_rows = await connection.fetch(
        """
        SELECT session_id::bigint AS session_id, external_quiz_id, COUNT(*)::int AS count
        FROM user_answers
        WHERE telegram_update_id BETWEEN $1 AND $2
        GROUP BY session_id, external_quiz_id
        HAVING COUNT(*) > 1
        ORDER BY session_id, external_quiz_id
        LIMIT 50
        """,
        start_update_id,
        end_update_id,
    )
    return duplicate_update_rows, duplicate_quiz_rows


async def _fetch_webhook_answer_outbox(
    connection: asyncpg.Connection, start_update_id: int, end_update_id: int,
) -> list[asyncpg.Record]:
    return await connection.fetch(
        """
        SELECT COALESCE(outbox.status, 'missing') AS status, COUNT(*)::int AS count
        FROM user_answers AS answer
        LEFT JOIN outbox_events AS outbox
          ON outbox.event_type = 'answer.accepted'
         AND outbox.aggregate_type = 'user_answer'
         AND outbox.aggregate_id = answer.id
        WHERE answer.telegram_update_id BETWEEN $1 AND $2
        GROUP BY COALESCE(outbox.status, 'missing')
        ORDER BY status
        """,
        start_update_id,
        end_update_id,
    )


async def _fetch_webhook_queue_validation(
    redis_client: Redis,
    *,
    stream_key: str,
    dead_letter_key: str,
    metrics_key_prefix: str,
) -> dict[str, Any]:
    stream_length = int(await redis_client.xlen(stream_key))
    dead_letter_length = int(await redis_client.xlen(dead_letter_key))
    pending, lag = await _redis_stream_group_backlog(redis_client, stream_key)
    lag_samples_raw = await redis_client.lrange(f"{metrics_key_prefix.rstrip(':')}:processing_lag_ms", 0, 9999)
    lag_samples = [_number_or_zero(value) for value in lag_samples_raw]
    dispatch_samples_raw = await redis_client.lrange(f"{metrics_key_prefix.rstrip(':')}:worker_dispatch_ms", 0, 9999)
    dispatch_samples = [_number_or_zero(value) for value in dispatch_samples_raw]
    return {
        "stream_key": stream_key,
        "dead_letter_key": dead_letter_key,
        "stream_length": stream_length,
        "dead_letter_length": dead_letter_length,
        "pending": pending,
        "lag": lag,
        "processing_lag_ms": _summarize_numeric(lag_samples),
        "worker_dispatch_ms": _summarize_numeric(dispatch_samples),
    }


async def _redis_stream_group_backlog(redis_client: Redis, stream_key: str) -> tuple[int, int | None]:
    try:
        groups = await redis_client.xinfo_groups(stream_key)
    except ResponseError as exc:
        if "no such key" in str(exc).lower():
            return 0, 0
        raise
    pending = 0
    lag_values: list[int] = []
    for group in groups:
        pending += int(group.get("pending") or 0)
        lag_raw = group.get("lag")
        if lag_raw is not None:
            lag_values.append(int(lag_raw))
    return pending, sum(lag_values) if lag_values else 0


async def _fetch_rows(connection: asyncpg.Connection, sql: str) -> list[dict[str, Any]]:
    return [dict(row) for row in await connection.fetch(sql)]


async def _fetch_rows_with_timeout(
    connection: asyncpg.Connection,
    sql: str,
    *,
    timeout_seconds: float,
) -> list[dict[str, Any]]:
    return await asyncio.wait_for(_fetch_rows(connection, sql), timeout=timeout_seconds)


def _summarize_postgres_lock_samples(
    samples: Sequence[Mapping[str, Any]],
    *,
    errors: Sequence[Mapping[str, str]],
) -> dict[str, Any]:
    counters = _postgres_summary_counters()
    maxima = _empty_postgres_maxima()
    max_samples: dict[str, Mapping[str, Any] | None] = {"active": None, "lock": None}
    for sample in samples:
        sample_counts = _postgres_sample_counts(sample)
        _update_postgres_maxima(sample, sample_counts, maxima, max_samples)
        _observe_postgres_activity(sample, counters)
        _observe_postgres_contention(sample, counters)
    return _postgres_summary_payload(samples, errors, counters, maxima, max_samples)


def _empty_postgres_maxima() -> dict[str, float]:
    return {
        "max_total_backends": 0.0,
        "max_active_backends": 0.0,
        "max_waiting_backends": 0.0,
        "max_active_waiting_backends": 0.0,
        "max_lock_waiting_backends": 0.0,
        "max_lwlock_waiting_backends": 0.0,
        "max_io_waiting_backends": 0.0,
        "max_client_waiting_backends": 0.0,
        "max_ungranted_locks": 0.0,
        "max_blocking_chains": 0.0,
    }


def _postgres_summary_counters() -> dict[str, Counter[Any]]:
    return {
        "all_wait_types": Counter(), "all_wait_events": Counter(),
        "active_wait_types": Counter(), "active_wait_events": Counter(),
        "lock_waits": Counter(), "blocking_queries": Counter(), "totals": Counter(),
    }


def _update_postgres_maxima(
    sample: Mapping[str, Any], counts: Mapping[str, int], maxima: dict[str, float],
    max_samples: dict[str, Mapping[str, Any] | None],
) -> None:
    if counts["max_active_waiting_backends"] > maxima.get("max_active_waiting_backends", 0):
        max_samples["active"] = sample
    if counts["max_lock_waiting_backends"] > maxima.get("max_lock_waiting_backends", 0):
        max_samples["lock"] = sample
    for name, value in counts.items():
        maxima[name] = max(maxima.get(name, 0.0), float(value))


def _observe_postgres_activity(sample: Mapping[str, Any], counters: dict[str, Counter[Any]]) -> None:
    totals = counters["totals"]
    for row in sample.get("activity", []):
        count = int(row.get("count") or 0)
        state = str(row.get("state") or "")
        wait_type = _none_label(row.get("wait_event_type"))
        wait_event = _none_label(row.get("wait_event"))
        totals["backend_observations"] += count
        if wait_type == "<none>":
            continue
        totals["wait_observations"] += count
        counters["all_wait_types"][(wait_type,)] += count
        counters["all_wait_events"][(wait_type, wait_event)] += count
        if state == "active":
            totals["active_wait_observations"] += count
            counters["active_wait_types"][(wait_type,)] += count
            counters["active_wait_events"][(wait_type, wait_event)] += count


def _observe_postgres_contention(sample: Mapping[str, Any], counters: dict[str, Counter[Any]]) -> None:
    totals = counters["totals"]
    for row in sample.get("lock_waits", []):
        key = (_none_label(row.get("relation")), _none_label(row.get("locktype")), _none_label(row.get("mode")))
        counters["lock_waits"][key] += 1
        totals["lock_wait_rows"] += 1
    for row in sample.get("blocking_chains", []):
        key = (_none_label(row.get("waiting_query_sample")), _none_label(row.get("blocking_query_sample")))
        counters["blocking_queries"][key] += 1
        totals["blocking_chain_rows"] += 1


def _postgres_summary_payload(
    samples: Sequence[Mapping[str, Any]], errors: Sequence[Mapping[str, str]],
    counters: dict[str, Counter[Any]], maxima: Mapping[str, float],
    max_samples: Mapping[str, Mapping[str, Any] | None],
) -> dict[str, Any]:
    totals = counters["totals"]
    return {
        "samples": len(samples),
        "errors": len(errors),
        **maxima,
        "backend_observations": totals["backend_observations"],
        "wait_observations": totals["wait_observations"],
        "active_wait_observations": totals["active_wait_observations"],
        "lock_wait_rows": totals["lock_wait_rows"],
        "blocking_chain_rows": totals["blocking_chain_rows"],
        "all_wait_types": _counter_rows(counters["all_wait_types"], ["wait_event_type"], totals["wait_observations"]),
        "all_wait_events": _counter_rows(
            counters["all_wait_events"],
            ["wait_event_type", "wait_event"],
            totals["wait_observations"],
        ),
        "active_wait_types": _counter_rows(
            counters["active_wait_types"],
            ["wait_event_type"],
            totals["active_wait_observations"],
        ),
        "active_wait_events": _counter_rows(
            counters["active_wait_events"],
            ["wait_event_type", "wait_event"],
            totals["active_wait_observations"],
        ),
        "lock_waits_by_relation": _counter_rows(
            counters["lock_waits"],
            ["relation", "locktype", "mode"],
            totals["lock_wait_rows"],
        ),
        "blocking_query_pairs": _counter_rows(
            counters["blocking_queries"],
            ["waiting_query_sample", "blocking_query_sample"],
            totals["blocking_chain_rows"],
            limit=10,
        ),
        "sample_at_max_active_waiting": _compact_postgres_sample(max_samples["active"]),
        "sample_at_max_lock_waiting": _compact_postgres_sample(max_samples["lock"]),
    }


def _postgres_sample_counts(sample: Mapping[str, Any]) -> dict[str, int]:
    activity = sample.get("activity", [])
    return {
        "max_total_backends": _activity_count(activity),
        "max_active_backends": _activity_count(activity, state="active"),
        "max_waiting_backends": _activity_count(activity, waiting=True),
        "max_active_waiting_backends": _activity_count(activity, state="active", waiting=True),
        "max_lock_waiting_backends": _activity_count(activity, wait_type="Lock"),
        "max_lwlock_waiting_backends": _activity_count(activity, wait_type="LWLock"),
        "max_io_waiting_backends": _activity_count(activity, wait_type="IO"),
        "max_client_waiting_backends": _activity_count(activity, wait_type="Client"),
        "max_ungranted_locks": len(sample.get("lock_waits", [])),
        "max_blocking_chains": len(sample.get("blocking_chains", [])),
    }


def _activity_count(
    activity: Sequence[Mapping[str, Any]], *, state: str | None = None,
    wait_type: str | None = None, waiting: bool = False,
) -> int:
    return sum(
        int(row.get("count") or 0)
        for row in activity
        if (state is None or row.get("state") == state)
        and (wait_type is None or row.get("wait_event_type") == wait_type)
        and (not waiting or row.get("wait_event_type") is not None)
    )


def _counter_rows(
    counter: Counter[tuple[str, ...]],
    field_names: Sequence[str],
    total: int,
    *,
    limit: int = 20,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for key, observations in counter.most_common(limit):
        row = {field_name: key[index] for index, field_name in enumerate(field_names)}
        row["observations"] = observations
        row["share"] = round(observations / total, 6) if total else 0.0
        rows.append(row)
    return rows


def _compact_postgres_sample(sample: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if sample is None:
        return None
    return {
        "offset_ms": sample.get("offset_ms"),
        "activity": sample.get("activity", []),
        "waiting_activity": sample.get("waiting_activity", []),
        "lock_waits": sample.get("lock_waits", []),
        "blocking_chains": sample.get("blocking_chains", []),
    }


def _none_label(value: object) -> str:
    return "<none>" if value is None else str(value)
