from __future__ import annotations



from scripts import load_stabilization_orchestrator as _root
globals().update({name: value for name, value in vars(_root).items() if not name.startswith("__")})


async def _sample_pgbouncer_until(
    stop_event: asyncio.Event,
    *,
    output_path: str,
    interval_ms: float,
    query_timeout_seconds: float,
) -> dict[str, Any]:
    target_database = os.environ.get("PGBOUNCER_TARGET_DATABASE", "")
    samples: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    config_rows: list[dict[str, str]] = []
    started_at = perf_counter()
    interval_seconds = max(interval_ms, 50.0) / 1000.0
    while not stop_event.is_set():
        sample_started = perf_counter()
        try:
            pools = await _run_pgbouncer_show("SHOW POOLS;", timeout_seconds=query_timeout_seconds)
            stats = await _run_pgbouncer_show("SHOW STATS;", timeout_seconds=query_timeout_seconds)
            if not config_rows:
                config_rows = await _run_pgbouncer_show("SHOW CONFIG;", timeout_seconds=query_timeout_seconds)
            samples.append(
                {
                    "offset_ms": round((sample_started - started_at) * 1000, 3),
                    "pools": pools,
                    "stats": stats,
                }
            )
        except Exception as exc:  # noqa: BLE001
            errors.append(
                {
                    "offset_ms": str(round((perf_counter() - started_at) * 1000, 3)),
                    "error": f"{exc.__class__.__name__}: {exc}",
                }
            )
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval_seconds)
        except asyncio.TimeoutError:
            continue

    payload = {
        "generated_at_utc": now_utc(),
        "target_database": target_database,
        "sample_interval_ms": interval_ms,
        "sample_count": len(samples),
        "samples": samples,
        "config": _pgbouncer_config_map(config_rows),
        "summary": _summarize_pgbouncer_samples(
            samples,
            config_rows=config_rows,
            target_database=target_database,
            errors=errors,
        ),
        "errors": errors,
    }
    _root.write_json(_root.resolve_evidence_path(output_path), payload)
    return payload["summary"]


async def _finish_sampler_task(
    task: asyncio.Task[dict[str, Any]],
    stop_event: asyncio.Event,
    *,
    sampler_name: str,
    output_path: str,
    stop_timeout_seconds: float,
) -> dict[str, Any]:
    stop_event.set()
    done, _pending = await asyncio.wait({task}, timeout=stop_timeout_seconds)
    if done:
        return _sampler_task_result(task, sampler_name=sampler_name, output_path=output_path)
    task.cancel()
    done, _pending = await asyncio.wait({task}, timeout=2.0)
    if done:
        try:
            task.result()
        except asyncio.CancelledError:
            pass
        except Exception as exc:  # noqa: BLE001
            return _write_sampler_failure_marker(
                sampler_name=sampler_name,
                output_path=output_path,
                measurement_timeout=False,
                timeout_seconds=stop_timeout_seconds,
                error=f"{exc.__class__.__name__}: {exc}",
            )
    return _write_sampler_failure_marker(
        sampler_name=sampler_name,
        output_path=output_path,
        measurement_timeout=True,
        timeout_seconds=stop_timeout_seconds,
        error=f"{sampler_name} sampler did not stop within {stop_timeout_seconds}s",
    )


def _sampler_task_result(
    task: asyncio.Task[dict[str, Any]],
    *,
    sampler_name: str,
    output_path: str,
) -> dict[str, Any]:
    try:
        return task.result()
    except asyncio.CancelledError:
        return _write_sampler_failure_marker(
            sampler_name=sampler_name,
            output_path=output_path,
            measurement_timeout=True,
            timeout_seconds=0.0,
            error=f"{sampler_name} sampler task was cancelled",
        )
    except Exception as exc:  # noqa: BLE001
        return _write_sampler_failure_marker(
            sampler_name=sampler_name,
            output_path=output_path,
            measurement_timeout=False,
            timeout_seconds=0.0,
            error=f"{exc.__class__.__name__}: {exc}",
        )


def _write_sampler_failure_marker(
    *,
    sampler_name: str,
    output_path: str,
    measurement_timeout: bool,
    timeout_seconds: float,
    error: str,
) -> dict[str, Any]:
    summary = {
        "sampler": sampler_name,
        "samples": 0,
        "errors": 1,
        "measurement_timeout": measurement_timeout,
        "timeout_seconds": timeout_seconds,
        "output_path": output_path,
    }
    payload = {
        "generated_at_utc": now_utc(),
        "sampler": sampler_name,
        "measurement_timeout": measurement_timeout,
        "timeout_seconds": timeout_seconds,
        "sample_count": 0,
        "samples": [],
        "summary": summary,
        "errors": [{"error": error}],
    }
    _root.write_json(_root.resolve_evidence_path(output_path), payload)
    return summary


async def _run_pgbouncer_show(sql: str, *, timeout_seconds: float) -> list[dict[str, str]]:
    container = _required_env("PGBOUNCER_ADMIN_DOCKER_CONTAINER")
    host = _required_env("PGBOUNCER_ADMIN_HOST")
    port = os.environ.get("PGBOUNCER_ADMIN_PORT", "6432")
    user = _required_env("PGBOUNCER_ADMIN_USER")
    password = _required_env("PGBOUNCER_ADMIN_PASSWORD")
    process = await asyncio.create_subprocess_exec(
        "docker",
        "exec",
        "-e",
        f"PGPASSWORD={password}",
        container,
        "psql",
        "--csv",
        "-X",
        "-q",
        "-P",
        "footer=off",
        "-h",
        host,
        "-p",
        port,
        "-U",
        user,
        "-d",
        "pgbouncer",
        "-c",
        sql,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        start_new_session=True,
    )
    stdout, stderr = await _communicate_sampler_process(process, timeout_seconds=timeout_seconds)
    if process.returncode != 0:
        message = stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(message or f"psql failed for {sql.strip()}")
    return _parse_csv_rows(stdout.decode("utf-8", errors="replace"))


async def _communicate_sampler_process(
    process: asyncio.subprocess.Process,
    *,
    timeout_seconds: float,
) -> tuple[bytes, bytes]:
    try:
        return await asyncio.wait_for(process.communicate(), timeout=timeout_seconds)
    except asyncio.TimeoutError as exc:
        _signal_async_process_tree(process, signal.SIGTERM)
        try:
            await asyncio.wait_for(process.communicate(), timeout=2.0)
        except asyncio.TimeoutError:
            _signal_async_process_tree(process, signal.SIGKILL)
            try:
                await asyncio.wait_for(process.communicate(), timeout=2.0)
            except asyncio.TimeoutError as kill_exc:
                raise RuntimeError(f"sampler subprocess {process.pid} did not exit after SIGKILL") from kill_exc
        raise RuntimeError(f"sampler subprocess timed out after {timeout_seconds}s") from exc


def _signal_async_process_tree(process: asyncio.subprocess.Process, sig: int) -> None:
    if process.returncode is not None:
        return
    try:
        os.killpg(process.pid, sig)
    except (OSError, ProcessLookupError):
        try:
            process.send_signal(sig)
        except (OSError, ProcessLookupError):
            return


def _required_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"{name} is required for PgBouncer sampling")
    return value


def _parse_csv_rows(raw: str) -> list[dict[str, str]]:
    if not raw.strip():
        return []
    reader = csv.DictReader(StringIO(raw))
    return [{str(key): str(value) for key, value in row.items()} for row in reader]


def _pgbouncer_config_map(rows: Sequence[Mapping[str, str]]) -> dict[str, str]:
    config: dict[str, str] = {}
    for row in rows:
        key = row.get("key") or row.get("name")
        value = row.get("value")
        if key is not None and value is not None:
            config[str(key)] = str(value)
    return config


def _summarize_pgbouncer_samples(
    samples: Sequence[Mapping[str, Any]],
    *,
    config_rows: Sequence[Mapping[str, str]],
    target_database: str,
    errors: Sequence[Mapping[str, str]],
) -> dict[str, Any]:
    pool_rows = [
        row
        for sample in samples
        for row in sample.get("pools", [])
        if not target_database or str(row.get("database", "")) == target_database
    ]
    config = _pgbouncer_config_map(config_rows)
    return {
        "target_database": target_database,
        "samples": len(samples),
        "pool_rows": len(pool_rows),
        "max_cl_active": _max_row_value(pool_rows, "cl_active"),
        "max_cl_waiting": _max_row_value(pool_rows, "cl_waiting"),
        "max_sv_active": _max_row_value(pool_rows, "sv_active"),
        "max_sv_idle": _max_row_value(pool_rows, "sv_idle"),
        "max_sv_used": _max_row_value(pool_rows, "sv_used"),
        "maxwait": _max_row_value(pool_rows, "maxwait"),
        "maxwait_us": _max_row_value(pool_rows, "maxwait_us"),
        "config": {
            name: config.get(name)
            for name in (
                "pool_mode",
                "max_client_conn",
                "default_pool_size",
                "max_db_connections",
                "reserve_pool_size",
                "reserve_pool_timeout",
                "server_lifetime",
                "query_timeout",
            )
            if name in config
        },
        "errors": len(errors),
    }

def _max_row_value(rows: Sequence[Mapping[str, str]], key: str) -> float:
    values = [_number_or_zero(row.get(key, "0")) for row in rows]
    return round(max(values), 3) if values else 0.0


def _number_or_zero(value: object) -> float:
    if value in (None, "", "NULL"):
        return 0.0
    try:
        return float(str(value))
    except ValueError:
        return 0.0


def _webhook_acceptance(
    *,
    error_total: int,
    statuses: Counter[int],
    latency_summary: Mapping[str, float],
    event_validation: Mapping[str, Any] | None,
    queue_processing: Mapping[str, Any] | None,
    args: argparse.Namespace,
) -> dict[str, Any]:
    criteria: dict[str, bool] = {
        "http_500_zero": statuses.get(500, 0) == 0,
        "http_non_2xx_zero": error_total == 0,
        "http_p95_ms_within_limit": latency_summary["p95"] <= args.max_http_p95_ms,
        "http_p99_ms_within_limit": latency_summary["p99"] <= args.max_http_p99_ms,
        "http_max_within_telegram_timeout": latency_summary["max"] <= args.telegram_timeout_ms,
    }
    if args.validate_events:
        criteria["event_validation_passed"] = bool(event_validation and event_validation.get("passed"))
        criteria["lost_events_zero"] = bool(event_validation and event_validation.get("lost_count") == 0)
        criteria["duplicate_update_answers_zero"] = bool(
            event_validation and event_validation.get("duplicate_update_count") == 0
        )
        criteria["duplicate_quiz_answers_zero"] = bool(
            event_validation and event_validation.get("duplicate_quiz_answer_count") == 0
        )
        criteria["queue_drained"] = bool(queue_processing and queue_processing.get("drained"))
        criteria["dead_letter_zero"] = bool(queue_processing and queue_processing.get("dead_letter_total") == 0)
        lag_ms = queue_processing.get("lag_ms", {}) if queue_processing else {}
        criteria["processing_lag_p95_within_limit"] = bool(
            isinstance(lag_ms, Mapping) and float(lag_ms.get("p95", 0.0)) <= args.max_processing_lag_p95_ms
        )
    return {
        "passed": all(criteria.values()),
        "criteria": criteria,
        "limits": {
            "max_http_p95_ms": args.max_http_p95_ms,
            "max_http_p99_ms": args.max_http_p99_ms,
            "telegram_timeout_ms": args.telegram_timeout_ms,
            "max_processing_lag_p95_ms": args.max_processing_lag_p95_ms,
        },
    }
