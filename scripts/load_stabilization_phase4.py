from __future__ import annotations



from scripts import load_stabilization_orchestrator as _root
globals().update({name: value for name, value in vars(_root).items() if not name.startswith("__")})


def _phase2_prepare(include_migration: bool) -> list[CommandSpec]:
    prepare = [default_worker_seed_command()]
    if include_migration:
        prepare.insert(0, default_migrate_command())
    return prepare


def _phase4_webhook_base(
    plan: Mapping[str, Any], session_offset: int,
) -> tuple[list[str], dict[str, str], str, str, float, float]:
    mode = str(plan.get("mode", "steady")).strip().lower()
    total_requests = str(plan.get("total_requests", 500))
    burst_interval_seconds = float(plan.get("burst_interval_seconds", 5.0))
    target_rps = str(plan.get("target_rps", max(1, round(int(total_requests) / burst_interval_seconds))))
    request_timeout_seconds = float(plan.get("timeout_seconds", 10.0))
    concurrency = str(plan.get("concurrency", total_requests if mode == "burst" else plan.get("target_rps", 100)))
    command = [
        "{python}",
        "scripts/load_stabilization_orchestrator.py",
        "webhook-load",
        "--base-url",
        "{ingress_base_url}",
        "--webhook-path",
        "{webhook_path}",
        "--secret-token",
        "{webhook_secret}",
        "--target-rps",
        "{target_rps}",
        "--total-requests",
        "{total_requests}",
        "--session-offset",
        "{session_offset}",
        "--seeded-session-count",
        "{seed_session_count}",
        "--concurrency",
        "{concurrency}",
        "--arrival-mode",
        "{arrival_mode}",
    ]
    context = {
        "target_rps": target_rps,
        "total_requests": total_requests,
        "session_offset": str(session_offset),
        "concurrency": concurrency,
        "arrival_mode": mode,
    }
    return command, context, mode, total_requests, burst_interval_seconds, request_timeout_seconds


def _add_webhook_arrival_options(
    plan: Mapping[str, Any], command: list[str], context: dict[str, str], mode: str,
) -> None:
    if mode == "burst":
        context["burst_window_seconds"] = str(plan.get("burst_window_seconds", 1.0))
        context["burst_interval_seconds"] = str(plan.get("burst_interval_seconds", 5.0))
        command.extend(
            [
                "--burst-window-seconds",
                "{burst_window_seconds}",
                "--burst-interval-seconds",
                "{burst_interval_seconds}",
            ]
        )
    if bool_setting(plan.get("target_app_replicas_direct"), False):
        command.extend(["--base-urls-csv", "{app_replica_urls_csv}"])
    else:
        command.extend(["--base-urls-csv", "{ingress_base_urls_csv}"])
    if "timeout_seconds" in plan:
        context["timeout_seconds"] = str(request_timeout_seconds)
        command.extend(["--timeout-seconds", "{timeout_seconds}"])
    if int(plan.get("warmup_connections", 0)) > 0:
        context["warmup_connections"] = str(plan["warmup_connections"])
        context["warmup_path"] = str(plan.get("warmup_path", "/health"))
        command.extend(
            [
                "--warmup-connections",
                "{warmup_connections}",
                "--warmup-path",
                "{warmup_path}",
            ]
        )
    if int(plan.get("client_shards", 1)) > 1:
        context["client_shards"] = str(plan["client_shards"])
        command.extend(["--client-shards", "{client_shards}"])


def _add_webhook_sampler_options(
    plan: Mapping[str, Any], command: list[str], context: dict[str, str], env: dict[str, str],
) -> None:
    if "pgbouncer_sample_output" in plan:
        context["pgbouncer_sample_output"] = str(plan["pgbouncer_sample_output"])
        context["pgbouncer_sample_interval_ms"] = str(plan.get("pgbouncer_sample_interval_ms", 250))
        command.extend(
            [
                "--pgbouncer-sample-output",
                "{pgbouncer_sample_output}",
                "--pgbouncer-sample-interval-ms",
                "{pgbouncer_sample_interval_ms}",
            ]
        )
        env.update(
            {
                "PGBOUNCER_ADMIN_DOCKER_CONTAINER": "{postgres_container}",
                "PGBOUNCER_ADMIN_HOST": "{pgbouncer_container}",
                "PGBOUNCER_ADMIN_PORT": "6432",
                "PGBOUNCER_ADMIN_USER": "{postgres_user}",
                "PGBOUNCER_ADMIN_PASSWORD": "{postgres_password}",
                "PGBOUNCER_TARGET_DATABASE": "{postgres_db}",
            }
        )
    if "postgres_lock_sample_output" in plan:
        context["postgres_lock_sample_output"] = str(plan["postgres_lock_sample_output"])
        context["postgres_lock_sample_interval_ms"] = str(plan.get("postgres_lock_sample_interval_ms", 500))
        command.extend(
            [
                "--postgres-lock-sample-output",
                "{postgres_lock_sample_output}",
                "--postgres-lock-sample-interval-ms",
                "{postgres_lock_sample_interval_ms}",
            ]
        )
        env["POSTGRES_LOCK_SAMPLE_DATABASE_URL"] = "{database_url_direct}"
    if "sampler_query_timeout_seconds" in plan:
        context["sampler_query_timeout_seconds"] = str(plan["sampler_query_timeout_seconds"])
        command.extend(["--sampler-query-timeout-seconds", "{sampler_query_timeout_seconds}"])
    if "sampler_stop_timeout_seconds" in plan:
        context["sampler_stop_timeout_seconds"] = str(plan["sampler_stop_timeout_seconds"])
        command.extend(["--sampler-stop-timeout-seconds", "{sampler_stop_timeout_seconds}"])


def _webhook_validation_context(plan: Mapping[str, Any]) -> dict[str, str]:
    defaults = {
        "queue_drain_timeout_seconds": 120.0,
        "queue_drain_poll_interval_seconds": 0.5,
        "max_http_p95_ms": 500.0,
        "max_http_p99_ms": 1500.0,
        "max_processing_lag_p95_ms": 3000.0,
        "telegram_timeout_ms": 30000.0,
        "webhook_ingress_stream_key": "dtb:webhook_ingress:updates",
        "webhook_ingress_dead_letter_key": "dtb:webhook_ingress:dead",
        "webhook_ingress_metrics_key_prefix": "dtb:webhook_ingress:metrics",
        "answer_persist_stream_key": "dtb:answer_persist:events",
        "answer_persist_dead_letter_key": "dtb:answer_persist:dead",
        "answer_persist_metrics_key_prefix": "dtb:answer_persist:metrics",
    }
    return {key: str(plan.get(key, value)) for key, value in defaults.items()}


def _add_webhook_validation_options(
    plan: Mapping[str, Any], command: list[str], context: dict[str, str],
) -> None:
    if bool_setting(plan.get("validate_events"), False):
        context.update(_webhook_validation_context(plan))
        command.extend(
            [
                "--validate-events",
                "--queue-drain-timeout-seconds",
                "{queue_drain_timeout_seconds}",
                "--queue-drain-poll-interval-seconds",
                "{queue_drain_poll_interval_seconds}",
                "--max-http-p95-ms",
                "{max_http_p95_ms}",
                "--max-http-p99-ms",
                "{max_http_p99_ms}",
                "--max-processing-lag-p95-ms",
                "{max_processing_lag_p95_ms}",
                "--telegram-timeout-ms",
                "{telegram_timeout_ms}",
                "--webhook-ingress-stream-key",
                "{webhook_ingress_stream_key}",
                "--webhook-ingress-dead-letter-key",
                "{webhook_ingress_dead_letter_key}",
                "--webhook-ingress-metrics-key-prefix",
                "{webhook_ingress_metrics_key_prefix}",
                "--answer-persist-stream-key",
                "{answer_persist_stream_key}",
                "--answer-persist-dead-letter-key",
                "{answer_persist_dead_letter_key}",
                "--answer-persist-metrics-key-prefix",
                "{answer_persist_metrics_key_prefix}",
            ]
        )


def _phase4_webhook_plan_command(
    plan: Mapping[str, Any],
    *,
    runtime: RuntimeSpec,
    session_offset: int,
) -> tuple[CommandSpec, bool]:
    assert runtime.stack is not None
    command, context, mode, total_requests, burst_interval, request_timeout = _phase4_webhook_base(
        plan, session_offset
    )
    env: dict[str, str] = {}
    _add_webhook_arrival_options(plan, command, context, mode)
    _add_webhook_sampler_options(plan, command, context, env)
    _add_webhook_validation_options(plan, command, context)
    return (
        CommandSpec(
            name=str(plan.get("name", f"{mode}_{total_requests}_requests")),
            command=command,
            parser="json",
            env=env,
            context=context,
            compare_paths=normalize_str_list(plan.get("compare_paths")) or list(PHASE4_WEBHOOK_COMPARE_PATHS),
            timeout_seconds=_phase4_webhook_measurement_timeout(
                plan,
                mode=mode,
                total_requests=int(total_requests),
                target_rps=float(context["target_rps"]),
                burst_window_seconds=float(context.get("burst_window_seconds", 1.0)),
                burst_interval_seconds=burst_interval,
                request_timeout_seconds=request_timeout,
            ),
        ),
        True,
    )


def _phase4_webhook_measurement_timeout(
    plan: Mapping[str, Any],
    *,
    mode: str,
    total_requests: int,
    target_rps: float,
    burst_window_seconds: float,
    burst_interval_seconds: float,
    request_timeout_seconds: float,
) -> float | None:
    explicit = plan.get("measurement_timeout_seconds")
    if explicit not in (None, ""):
        return float(explicit)
    queue_drain_timeout = (
        float(plan.get("queue_drain_timeout_seconds", 120.0))
        if bool_setting(plan.get("validate_events"), False)
        else 0.0
    )
    scheduled_span = _root._scheduled_offset(
        max(total_requests - 1, 0),
        target_rps=max(target_rps, 0.001),
        mode=mode,
        burst_window=burst_window_seconds,
        burst_interval=burst_interval_seconds,
    )
    return round(max(60.0, scheduled_span + request_timeout_seconds + queue_drain_timeout + 120.0), 3)


def phase4_plan_command(
    plan: Mapping[str, Any],
    *,
    runtime: RuntimeSpec,
    session_offset: int = 0,
) -> tuple[CommandSpec, bool]:
    mode = str(plan.get("mode", "")).strip().lower()
    if mode not in {"steady", "burst"}:
        raise ValueError("phase4 plans require mode=steady or mode=burst")
    if "command" in plan:
        return command_spec_from_raw(plan), False
    if runtime.stack is not None:
        return _phase4_webhook_plan_command(plan, runtime=runtime, session_offset=session_offset)
    if mode != "steady":
        raise ValueError("burst plans require an explicit command")
    target_rps = str(plan.get("target_rps", 25))
    total_requests = str(plan.get("total_requests", 500))
    workers_on = bool_setting(plan.get("workers_on"), False)
    command = [
        "{python}",
        "scripts/worker_pipeline_v2_regression_isolation.py",
        "run",
        "--target-rps",
        "{target_rps}",
        "--total-requests",
        "{total_requests}",
        "--session-offset",
        "{session_offset}",
        "--seeded-session-count",
        "{seed_session_count}",
    ]
    if workers_on:
        command.append("--workers-on")
    return (
        CommandSpec(
            name=str(plan.get("name", f"steady_{target_rps}_rps")),
            command=command,
            parser="json",
            env={
                "DATABASE_URL": "{database_url_app}",
                "TEST_DATABASE_URL": "{database_url_direct}",
                "DB_CONNECTION_BACKEND": "{app_backend}",
            },
            context={
                "target_rps": target_rps,
                "total_requests": total_requests,
                "session_offset": str(session_offset),
            },
            compare_paths=list(PHASE4_STEADY_COMPARE_PATHS),
        ),
        True,
    )


def phase4_variants(spec: Mapping[str, Any]) -> list[RuntimeSpec]:
    raw_variants = spec.get("variants")
    plans = spec.get("plans")
    if not isinstance(raw_variants, list) or not raw_variants:
        raise ValueError("phase4 requires a non-empty variants array")
    if not isinstance(plans, list) or not plans:
        raise ValueError("phase4 requires a non-empty plans array")
    defaults = BuildDefaults(
        default_env=normalize_str_map(spec.get("env")),
        default_context={},
        default_postgres_settings=normalize_str_map(spec.get("postgres_settings")),
        default_redis_args=normalize_str_list(spec.get("redis_args")),
        default_pgbouncer=merge_pgbouncer(spec.get("pgbouncer"), None),
        default_stack=merge_stack_spec(spec.get("stack"), None),
        default_prepare=(
            ([default_migrate_command()] if bool_setting(spec.get("migrate"), True) else [])
            + build_custom_measurements(spec.get("prepare", []))
        ),
        default_measurements=[],
        top_level_images={
            "postgres_image": str(spec.get("postgres_image", "postgres:16-alpine")),
            "redis_image": str(spec.get("redis_image", "redis:7-alpine")),
            "pgbouncer_image": str(spec.get("pgbouncer_image", "edoburu/pgbouncer:latest")),
        },
        top_level_runtime={
            "postgres_user": str(spec.get("postgres_user", "postgres")),
            "postgres_password": str(spec.get("postgres_password", "postgres")),
            "postgres_shm_size": str(spec.get("postgres_shm_size", "128m")),
            "ready_timeout_seconds": float(spec.get("ready_timeout_seconds", 60.0)),
        },
    )
    variants: list[RuntimeSpec] = []
    for raw in raw_variants:
        runtime = build_runtime_spec(raw, defaults)
        if raw.get("measurements"):
            variants.append(runtime)
            continue
        measurement_specs: list[CommandSpec] = []
        needs_seed = False
        next_session_offset = 0
        for plan in plans:
            command_spec, plan_needs_seed = phase4_plan_command(
                plan,
                runtime=runtime,
                session_offset=next_session_offset,
            )
            measurement_specs.append(command_spec)
            needs_seed = needs_seed or plan_needs_seed
            if plan_needs_seed:
                next_session_offset += int(command_spec.context["total_requests"])
        runtime.measurements = measurement_specs
        runtime.context["seed_session_count"] = str(
            _seed_session_count(runtime.prepare, runtime.measurements, override=raw.get("seed_session_count"))
        )
        if needs_seed:
            runtime.prepare.append(default_worker_seed_command())
        variants.append(runtime)
    return variants
