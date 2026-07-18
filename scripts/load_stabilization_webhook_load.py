from __future__ import annotations



from scripts import load_stabilization_orchestrator as _root
globals().update({name: value for name, value in vars(_root).items() if not name.startswith("__")})


def _webhook_base_urls(args: argparse.Namespace) -> list[str]:
    urls = [item.strip().rstrip("/") for item in args.base_urls_csv.split(",") if item.strip()]
    return urls or [args.base_url.rstrip("/")]


def _validate_webhook_load_args(args: argparse.Namespace) -> None:
    checks = [
        (args.arrival_mode == "burst" and args.burst_window_seconds > args.burst_interval_seconds,
         "--burst-window-seconds must be less than or equal to --burst-interval-seconds"),
        (args.session_offset < 0, "--session-offset must be greater than or equal to 0"),
        (args.seeded_session_count <= 0, "--seeded-session-count must be greater than 0"),
        (args.total_requests <= 0, "--total-requests must be greater than 0"),
        (args.concurrency <= 0, "--concurrency must be greater than 0"),
        (args.client_shards <= 0, "--client-shards must be greater than 0"),
        (args.warmup_connections < 0, "--warmup-connections must be greater than or equal to 0"),
        (args.validate_events and args.queue_drain_timeout_seconds <= 0,
         "--queue-drain-timeout-seconds must be greater than 0"),
        (args.validate_events and args.queue_drain_poll_interval_seconds <= 0,
         "--queue-drain-poll-interval-seconds must be greater than 0"),
        (args.sampler_stop_timeout_seconds <= 0, "--sampler-stop-timeout-seconds must be greater than 0"),
        (args.sampler_query_timeout_seconds <= 0, "--sampler-query-timeout-seconds must be greater than 0"),
        (args.session_offset + args.total_requests > args.seeded_session_count,
         "configured session selection exceeds seeded session capacity"),
    ]
    for failed, message in checks:
        if failed:
            raise SystemExit(message)


def _start_webhook_samplers(args: argparse.Namespace) -> dict[str, dict[str, Any]]:
    samplers: dict[str, dict[str, Any]] = {}
    if args.pgbouncer_sample_output:
        event = asyncio.Event()
        samplers["pgbouncer"] = {
            "event": event,
            "output": args.pgbouncer_sample_output,
            "task": asyncio.create_task(_sample_pgbouncer_until(
                event, output_path=args.pgbouncer_sample_output,
                interval_ms=args.pgbouncer_sample_interval_ms,
                query_timeout_seconds=args.sampler_query_timeout_seconds,
            )),
        }
    if args.postgres_lock_sample_output:
        event = asyncio.Event()
        samplers["postgres_lock"] = {
            "event": event,
            "output": args.postgres_lock_sample_output,
            "task": asyncio.create_task(_sample_postgres_lock_profile_until(
                event, output_path=args.postgres_lock_sample_output,
                interval_ms=args.postgres_lock_sample_interval_ms,
                query_timeout_seconds=args.sampler_query_timeout_seconds,
            )),
        }
    return samplers


async def _stop_webhook_samplers(
    samplers: Mapping[str, Mapping[str, Any]], args: argparse.Namespace,
) -> dict[str, dict[str, Any]]:
    summaries: dict[str, dict[str, Any]] = {}
    for name, sampler in samplers.items():
        summaries[name] = await _finish_sampler_task(
            sampler["task"], sampler["event"], sampler_name=name,
            output_path=sampler["output"],
            stop_timeout_seconds=args.sampler_stop_timeout_seconds,
        )
    return summaries


def _new_webhook_metrics(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "latencies": [], "dispatch": [], "statuses": Counter(), "errors": Counter(),
        "semaphore": asyncio.Semaphore(args.concurrency), "lock": asyncio.Lock(),
        "in_flight": 0, "max_in_flight": 0,
    }

async def _invoke_webhook_request(
    client: ClientSession, args: argparse.Namespace, base_urls: Sequence[str],
    metrics: dict[str, Any], *, index: int, started_at: float,
) -> None:
    scheduled_at = _scheduled_offset(
        index, target_rps=args.target_rps, mode=args.arrival_mode,
        burst_window=args.burst_window_seconds, burst_interval=args.burst_interval_seconds,
    )
    now_offset = perf_counter() - started_at
    if scheduled_at > now_offset:
        await asyncio.sleep(scheduled_at - now_offset)
    dispatch_started = perf_counter()
    metrics["dispatch"].append(round((dispatch_started - started_at - scheduled_at) * 1000, 3))
    async with metrics["semaphore"]:
        async with metrics["lock"]:
            metrics["in_flight"] += 1
            metrics["max_in_flight"] = max(metrics["max_in_flight"], metrics["in_flight"])
        request_started = perf_counter()
        try:
            session_id = _measurement_session_id(args.session_offset, index)
            response = await client.post(
                f"{base_urls[index % len(base_urls)]}{args.webhook_path}",
                headers={
                    "Content-Type": "application/json",
                    "X-Telegram-Bot-Api-Secret-Token": args.secret_token,
                },
                json=_build_answer_callback_update(
                    args.start_update_id + index, session_id=session_id,
                    telegram_user_id=args.base_user_id + session_id,
                    selected_option_id=args.selected_option_id,
                ),
            )
            async with response:
                await response.read()
                metrics["statuses"][response.status] += 1
        except (ClientError, TimeoutError, OSError, asyncio.TimeoutError) as exc:
            metrics["errors"][exc.__class__.__name__] += 1
        else:
            metrics["latencies"].append(round((perf_counter() - request_started) * 1000, 3))
        finally:
            async with metrics["lock"]:
                metrics["in_flight"] -= 1


async def _wait_for_webhook_start(start_at_epoch_ms: int | None) -> None:
    if start_at_epoch_ms is None:
        return
    delay = (start_at_epoch_ms / 1000) - time.time()
    if delay > 0:
        await asyncio.sleep(delay)


async def _run_single_webhook_load(
    args: argparse.Namespace, base_urls: Sequence[str],
) -> dict[str, Any]:
    timeout = ClientTimeout(total=args.timeout_seconds)
    connector = TCPConnector(
        limit=args.concurrency, limit_per_host=args.concurrency, enable_cleanup_closed=True,
    )
    metrics = _new_webhook_metrics(args)
    warmup = None
    validation = None
    async with ClientSession(timeout=timeout, connector=connector) as client:
        if args.warmup_connections > 0:
            warmup = await _warmup_http_connections(
                client, base_urls=base_urls, path=args.warmup_path,
                total_connections=args.warmup_connections, concurrency=args.concurrency,
            )
        await _wait_for_webhook_start(args.start_at_epoch_ms)
        started_at = perf_counter()
        await asyncio.gather(*(
            _invoke_webhook_request(
                client, args, base_urls, metrics, index=index, started_at=started_at,
            )
            for index in range(args.total_requests)
        ))
        if args.validate_events:
            validation = await _validate_webhook_processing(args)
    return {
        "metrics": metrics, "warmup": warmup, "validation": validation,
        "elapsed": perf_counter() - started_at,
    }


def _webhook_request_summary(
    args: argparse.Namespace, statuses: Counter[int], errors: Counter[str],
) -> tuple[dict[str, Any], int]:
    accepted = sum(count for status, count in statuses.items() if 200 <= status < 300)
    return {
        "requested": args.total_requests,
        "accepted": accepted,
        "errors": args.total_requests - accepted,
        "success_rate": round(accepted / args.total_requests, 6) if args.total_requests else 0.0,
        "status_counts": {str(status): count for status, count in sorted(statuses.items())},
        "error_types": dict(errors),
    }, accepted


def _webhook_arrival_summary(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "mode": args.arrival_mode,
        "burst_window_seconds": None if args.arrival_mode == "steady" else args.burst_window_seconds,
        "burst_interval_seconds": None if args.arrival_mode == "steady" else args.burst_interval_seconds,
        "scheduled_dispatch_span_sec": round(_scheduled_offset(
            max(args.total_requests - 1, 0), target_rps=args.target_rps,
            mode=args.arrival_mode, burst_window=args.burst_window_seconds,
            burst_interval=args.burst_interval_seconds,
        ), 3),
    }


def _webhook_harness_summary(
    args: argparse.Namespace, base_urls: Sequence[str], *, elapsed: float,
    max_in_flight: int, client_shards: int,
) -> dict[str, Any]:
    return {
        "open_loop_target_rps": args.target_rps,
        "arrival_mode": args.arrival_mode,
        "target_base_url_count": len(base_urls),
        "client_shards": client_shards,
        "achieved_rps": round(args.total_requests / max(elapsed, 0.001), 3),
        "max_in_flight_requests": max_in_flight,
        "sampler_query_timeout_seconds": args.sampler_query_timeout_seconds,
        "sampler_stop_timeout_seconds": args.sampler_stop_timeout_seconds,
        "event_loop": asyncio.get_running_loop().__class__.__module__,
    }


def _build_webhook_result(
    args: argparse.Namespace, base_urls: Sequence[str], execution: Mapping[str, Any],
    sampler_summaries: Mapping[str, Mapping[str, Any]], *, client_shards: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    metrics = execution["metrics"]
    validation = execution.get("validation")
    queue_processing = validation.pop("queue_processing", None) if validation is not None else None
    requests, accepted = _webhook_request_summary(args, metrics["statuses"], metrics["errors"])
    latency = _summarize_numeric(metrics["latencies"])
    acceptance = _webhook_acceptance(
        error_total=args.total_requests - accepted, statuses=metrics["statuses"],
        latency_summary=latency, event_validation=validation,
        queue_processing=queue_processing, args=args,
    )
    result = {
        "requests": requests, "arrival": _webhook_arrival_summary(args),
        "latency_ms": latency, "answer_p95_ms": latency["p95"], "acceptance": acceptance,
        "dispatch_lag_ms": _summarize_numeric(metrics["dispatch"]),
        "harness_validation": _webhook_harness_summary(
            args, base_urls, elapsed=execution["elapsed"],
            max_in_flight=metrics["max_in_flight"], client_shards=client_shards,
        ),
    }
    _attach_webhook_evidence(
        result, execution, sampler_summaries, validation, queue_processing,
    )
    return result, acceptance


def _attach_webhook_evidence(
    result: dict[str, Any], execution: Mapping[str, Any],
    samplers: Mapping[str, Mapping[str, Any]], validation: Mapping[str, Any] | None,
    queue_processing: Mapping[str, Any] | None,
) -> None:
    optional = {
        "event_validation": validation,
        "queue_processing": queue_processing,
        "connection_warmup": execution.get("warmup"),
        "pgbouncer_admin_sampling": samplers.get("pgbouncer"),
        "postgres_lock_sampling": samplers.get("postgres_lock"),
        "client_shard_summaries": execution.get("child_summaries"),
    }
    for key, value in optional.items():
        if value is not None:
            result[key] = value
    if execution.get("emit_samples"):
        result["latency_samples_ms"] = execution["metrics"]["latencies"]
        result["dispatch_lag_samples_ms"] = execution["metrics"]["dispatch"]


async def webhook_load(args: argparse.Namespace) -> int:
    base_urls = _webhook_base_urls(args)
    _validate_webhook_load_args(args)
    if args.client_shards > 1:
        return await _webhook_load_sharded(args, base_urls=base_urls)
    samplers = _start_webhook_samplers(args)
    try:
        execution = await _run_single_webhook_load(args, base_urls)
    finally:
        sampler_summaries = await _stop_webhook_samplers(samplers, args)
    execution["emit_samples"] = args.emit_samples
    result, acceptance = _build_webhook_result(
        args, base_urls, execution, sampler_summaries, client_shards=1,
    )
    print(json.dumps(result, indent=2, ensure_ascii=True))
    return 0 if acceptance["passed"] else 1


def _aggregate_webhook_shards(
    child_results: Sequence[Mapping[str, Any]], args: argparse.Namespace,
) -> dict[str, Any]:
    metrics = _new_webhook_metrics(args)
    metrics["max_in_flight"] = 0
    warmup = {"requested": 0, "accepted": 0, "errors": 0}
    child_summaries: list[dict[str, Any]] = []
    for child in child_results:
        payload = child["payload"]
        child_summaries.append({
            "shard_index": child["shard_index"], "returncode": child["returncode"],
            "requests": payload.get("requests"), "latency_ms": payload.get("latency_ms"),
            "dispatch_lag_ms": payload.get("dispatch_lag_ms"),
            "connection_warmup": payload.get("connection_warmup"),
        })
        metrics["latencies"].extend(float(value) for value in payload.get("latency_samples_ms", []))
        metrics["dispatch"].extend(float(value) for value in payload.get("dispatch_lag_samples_ms", []))
        requests = payload.get("requests", {})
        metrics["statuses"].update({int(key): int(value) for key, value in requests.get("status_counts", {}).items()})
        metrics["errors"].update({str(key): int(value) for key, value in requests.get("error_types", {}).items()})
        metrics["max_in_flight"] += int(payload.get("harness_validation", {}).get("max_in_flight_requests") or 0)
        child_warmup = payload.get("connection_warmup") or {}
        for key in warmup:
            warmup[key] += int(child_warmup.get(key) or 0)
    return {"metrics": metrics, "warmup": warmup, "child_summaries": child_summaries}


async def _webhook_load_sharded(args: argparse.Namespace, *, base_urls: Sequence[str]) -> int:
    started_at = perf_counter()
    samplers = _start_webhook_samplers(args)
    validation = None
    try:
        start_at_epoch_ms = int((time.time() + 15.0) * 1000)
        children = await asyncio.gather(*(
            _run_webhook_load_shard(args, shard_index=index, start_at_epoch_ms=start_at_epoch_ms)
            for index in range(args.client_shards)
        ))
        if args.validate_events:
            validation = await _validate_webhook_processing(args)
    finally:
        sampler_summaries = await _stop_webhook_samplers(samplers, args)
    execution = _aggregate_webhook_shards(children, args)
    execution.update({"validation": validation, "elapsed": perf_counter() - started_at})
    result, acceptance = _build_webhook_result(
        args, base_urls, execution, sampler_summaries, client_shards=args.client_shards,
    )
    print(json.dumps(result, indent=2, ensure_ascii=True))
    return 0 if acceptance["passed"] else 1


def _webhook_shard_argv(
    args: argparse.Namespace, *, script_path: Path, shard_index: int, start_at_epoch_ms: int,
) -> list[str]:
    total = _shard_size(args.total_requests, args.client_shards, shard_index)
    offset = _shard_offset(args.total_requests, args.client_shards, shard_index)
    warmup = _shard_size(args.warmup_connections, args.client_shards, shard_index)
    concurrency = max(1, min(total, math.ceil(args.concurrency / args.client_shards)))
    target_rps = max(1.0, args.target_rps * (total / args.total_requests))
    pairs = [
        ("--base-url", args.base_url), ("--base-urls-csv", args.base_urls_csv),
        ("--webhook-path", args.webhook_path), ("--secret-token", args.secret_token),
        ("--target-rps", target_rps), ("--total-requests", total),
        ("--session-offset", args.session_offset + offset),
        ("--seeded-session-count", args.seeded_session_count),
        ("--selected-option-id", args.selected_option_id), ("--concurrency", concurrency),
        ("--arrival-mode", args.arrival_mode), ("--burst-window-seconds", args.burst_window_seconds),
        ("--burst-interval-seconds", args.burst_interval_seconds),
        ("--timeout-seconds", args.timeout_seconds), ("--warmup-connections", warmup),
        ("--warmup-path", args.warmup_path), ("--start-update-id", args.start_update_id + offset),
        ("--base-user-id", args.base_user_id), ("--start-at-epoch-ms", start_at_epoch_ms),
    ]
    argv = [sys.executable, str(script_path), "webhook-load"]
    for option, value in pairs:
        argv.extend([option, str(value)])
    return [*argv, "--emit-samples"]


def _parse_webhook_shard_payload(
    stdout: str, stderr: str, *, shard_index: int, returncode: int | None,
) -> dict[str, Any]:
    try:
        json_start = stdout.find("{")
        if json_start < 0:
            raise ValueError("JSON object not found in shard stdout")
        return json.loads(stdout[json_start:])
    except Exception as exc:
        raise RuntimeError(
            f"webhook load shard {shard_index} failed to produce JSON: "
            f"returncode={returncode} stderr={stderr[:1000]!r}"
        ) from exc


async def _run_webhook_load_shard(
    args: argparse.Namespace, *, shard_index: int, start_at_epoch_ms: int,
) -> dict[str, Any]:
    script_path = Path(__file__).resolve()
    process = await asyncio.create_subprocess_exec(
        *_webhook_shard_argv(
            args, script_path=script_path, shard_index=shard_index,
            start_at_epoch_ms=start_at_epoch_ms,
        ),
        cwd=str(script_path.parent.parent),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout_bytes, stderr_bytes = await process.communicate()
    payload = _parse_webhook_shard_payload(
        stdout_bytes.decode("utf-8", errors="replace"),
        stderr_bytes.decode("utf-8", errors="replace"),
        shard_index=shard_index, returncode=process.returncode,
    )
    return {"shard_index": shard_index, "returncode": process.returncode, "payload": payload}


def _shard_size(total: int, shard_count: int, shard_index: int) -> int:
    base = total // shard_count
    remainder = total % shard_count
    return base + (1 if shard_index < remainder else 0)


def _shard_offset(total: int, shard_count: int, shard_index: int) -> int:
    return sum(_shard_size(total, shard_count, index) for index in range(shard_index))


async def _warmup_http_connections(
    client: ClientSession,
    *,
    base_urls: Sequence[str],
    path: str,
    total_connections: int,
    concurrency: int,
) -> dict[str, Any]:
    normalized_path = path if path.startswith("/") else f"/{path}"
    statuses: Counter[int] = Counter()
    errors: Counter[str] = Counter()
    latencies_ms: list[float] = []
    semaphore = asyncio.Semaphore(max(1, concurrency))

    async def warm(index: int) -> None:
        async with semaphore:
            request_started = perf_counter()
            try:
                response = await client.get(f"{base_urls[index % len(base_urls)]}{normalized_path}")
                async with response:
                    await response.read()
                    statuses[response.status] += 1
            except (ClientError, TimeoutError, OSError, asyncio.TimeoutError) as exc:
                errors[exc.__class__.__name__] += 1
            else:
                latencies_ms.append(round((perf_counter() - request_started) * 1000, 3))

    await asyncio.gather(*(warm(index) for index in range(total_connections)))
    accepted = sum(count for status, count in statuses.items() if 200 <= status < 300)
    return {
        "path": normalized_path,
        "requested": total_connections,
        "accepted": accepted,
        "errors": total_connections - accepted,
        "status_counts": {str(status): count for status, count in sorted(statuses.items())},
        "error_types": dict(errors),
        "latency_ms": _summarize_numeric(latencies_ms),
        "target_base_url_count": len(base_urls),
    }
