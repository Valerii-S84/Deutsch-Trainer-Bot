from __future__ import annotations

import argparse
import asyncio
import csv
from collections import Counter
import json
import math
import os
from io import StringIO
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from time import perf_counter
from typing import Any

import httpx

try:
    from load_stabilization_support import (
        CommandSpec,
        DockerBuildSpec,
        DockerRuntime,
        RuntimeSpec,
        ServiceSpec,
        WebhookStackSpec,
        build_comparisons,
        gather_docker_version,
        gather_repo_state,
        normalize_command,
        normalize_str_list,
        normalize_str_map,
        now_utc,
        resolve_evidence_path,
        run_command_spec,
        sanitize_name,
        write_json,
    )
except ImportError:  # pragma: no cover - package import path for tests
    from scripts.load_stabilization_support import (
        CommandSpec,
        DockerBuildSpec,
        DockerRuntime,
        RuntimeSpec,
        ServiceSpec,
        WebhookStackSpec,
        build_comparisons,
        gather_docker_version,
        gather_repo_state,
        normalize_command,
        normalize_str_list,
        normalize_str_map,
        now_utc,
        resolve_evidence_path,
        run_command_spec,
        sanitize_name,
        write_json,
    )


PHASE1_COMPARE_PATHS = ["p95", "throughput_per_sec", "errors", "samples"]
PHASE4_STEADY_COMPARE_PATHS = [
    "requests.accepted",
    "requests.errors",
    "latency_ms.p95",
    "db_acquire_wait_ms.p95",
    "harness_validation.achieved_rps",
]
PHASE4_WEBHOOK_COMPARE_PATHS = [
    "requests.accepted",
    "requests.errors",
    "requests.success_rate",
    "answer_p95_ms",
    "latency_ms.p95",
    "harness_validation.achieved_rps",
]
CALLBACK_TRAIN_ANSWER_PREFIX = "train:ans"
LOADTEST_BOT_USER_ID = 123456789


@dataclass(slots=True)
class BuildDefaults:
    default_env: dict[str, str]
    default_context: dict[str, str]
    default_postgres_settings: dict[str, str]
    default_redis_args: list[str]
    default_pgbouncer: dict[str, str] | None
    default_stack: WebhookStackSpec | None = None
    default_prepare: list[CommandSpec] = field(default_factory=list)
    default_measurements: list[CommandSpec] = field(default_factory=list)
    top_level_images: dict[str, str] = field(default_factory=dict)
    top_level_runtime: dict[str, Any] = field(default_factory=dict)


def load_spec(spec_file: str | None, spec_json: str | None) -> dict[str, Any]:
    if bool(spec_file) == bool(spec_json):
        raise ValueError("Provide exactly one of --spec-file or --spec-json")
    if spec_json:
        payload = json.loads(spec_json)
    else:
        with open(spec_file, encoding="utf-8") as handle:
            payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError("Spec payload must be a JSON object")
    return payload


def add_spec_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--spec-file", help="Path to a JSON phase spec.")
    parser.add_argument("--spec-json", help="Inline JSON phase spec.")


def bool_setting(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    lowered = str(value).strip().lower()
    if lowered in {"1", "true", "yes", "on"}:
        return True
    if lowered in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"Invalid boolean value: {value}")


def stage_setting(value: Any) -> str:
    if value is None:
        return "before_stack"
    stage = str(value).strip().lower()
    if stage not in {"before_stack", "after_stack"}:
        raise ValueError("command stage must be before_stack or after_stack")
    return stage


def command_spec_from_raw(raw: Mapping[str, Any]) -> CommandSpec:
    if "name" not in raw or "command" not in raw:
        raise ValueError("Every command requires name and command")
    return CommandSpec(
        name=str(raw["name"]),
        command=normalize_command(raw["command"]),
        parser=str(raw.get("parser", "text")),
        env=normalize_str_map(raw.get("env")),
        context=normalize_str_map(raw.get("context")),
        compare_paths=normalize_str_list(raw.get("compare_paths")),
        allow_failure=bool_setting(raw.get("allow_failure"), False),
        stage=stage_setting(raw.get("stage")),
    )


def default_migrate_command() -> CommandSpec:
    return CommandSpec(
        name="migrate",
        command=["{python}", "-m", "alembic", "upgrade", "head"],
        parser="text",
        env={
            "DATABASE_URL": "{database_url_direct}",
            "TEST_DATABASE_URL": "{database_url_direct}",
            "DB_CONNECTION_BACKEND": "direct",
        },
    )


def default_phase1_measurement(spec: Mapping[str, Any]) -> CommandSpec:
    requests = str(spec.get("requests", 500))
    operations = str(spec.get("operations", "select1,insert_simple"))
    concurrency = str(spec.get("concurrency", "10,25,50,100"))
    pool_configs = str(spec.get("pool_configs", "10:10"))
    pool_timeouts = str(spec.get("pool_timeouts", "5"))
    return CommandSpec(
        name="db_pool_microbench",
        command=[
            "{python}",
            "scripts/db_pool_microbench.py",
            "--requests",
            "{requests}",
            "--operations",
            "{operations}",
            "--concurrency",
            "{concurrency}",
            "--pool-configs",
            "{pool_configs}",
            "--pool-timeouts",
            "{pool_timeouts}",
        ],
        parser="json",
        context={
            "requests": requests,
            "operations": operations,
            "concurrency": concurrency,
            "pool_configs": pool_configs,
            "pool_timeouts": pool_timeouts,
        },
        compare_paths=["results"],
    )


def default_worker_seed_command() -> CommandSpec:
    return CommandSpec(
        name="seed_worker_pipeline",
        command=[
            "{python}",
            "scripts/worker_pipeline_v2_regression_isolation.py",
            "seed",
            "--session-count",
            "{seed_session_count}",
        ],
        parser="json",
        env={
            "DATABASE_URL": "{database_url_direct}",
            "TEST_DATABASE_URL": "{database_url_direct}",
            "DB_CONNECTION_BACKEND": "direct",
        },
    )


def default_phase2_measurements(spec: Mapping[str, Any]) -> list[CommandSpec]:
    total_requests = str(spec.get("total_requests", 500))
    total_requests_value = int(total_requests)
    rps_points = normalize_str_list(spec.get("rps_points")) or ["10", "25", "50", "100"]
    measurements: list[CommandSpec] = []
    for index, rps in enumerate(rps_points):
        session_offset = str(index * total_requests_value)
        measurements.append(
            CommandSpec(
            name=f"workers_off_{rps}_rps",
            command=[
                "{python}",
                "scripts/worker_pipeline_v2_regression_isolation.py",
                "run",
                "--target-rps",
                "{target_rps}",
                "--total-requests",
                "{total_requests}",
                "--session-offset",
                "{session_offset}",
            ],
            parser="json",
            env={
                "DATABASE_URL": "{database_url_app}",
                "TEST_DATABASE_URL": "{database_url_direct}",
                "DB_CONNECTION_BACKEND": "{app_backend}",
            },
            context={
                "target_rps": rps,
                "total_requests": total_requests,
                "session_offset": session_offset,
            },
            compare_paths=[
                "requests.accepted",
                "requests.errors",
                "latency_ms.p95",
                "db_acquire_wait_ms.p95",
            ],
        )
        )
    return measurements


def build_custom_measurements(raw_items: Sequence[Mapping[str, Any]]) -> list[CommandSpec]:
    return [command_spec_from_raw(item) for item in raw_items]


def clone_build_spec(spec: DockerBuildSpec | None) -> DockerBuildSpec | None:
    if spec is None:
        return None
    return DockerBuildSpec(context=spec.context, dockerfile=spec.dockerfile)


def clone_service_spec(spec: ServiceSpec) -> ServiceSpec:
    return ServiceSpec(
        runner=spec.runner,
        replicas=spec.replicas,
        command=list(spec.command),
        env=dict(spec.env),
        image=spec.image,
        build=clone_build_spec(spec.build),
        listen_port=spec.listen_port,
        ready_path=spec.ready_path,
        workdir=spec.workdir,
        extra_args=list(spec.extra_args),
    )


def clone_stack_spec(spec: WebhookStackSpec | None) -> WebhookStackSpec | None:
    if spec is None:
        return None
    return WebhookStackSpec(
        mode=spec.mode,
        webhook_path=spec.webhook_path,
        webhook_secret=spec.webhook_secret,
        app=clone_service_spec(spec.app),
        worker=clone_service_spec(spec.worker),
        ingress=None if spec.ingress is None else clone_service_spec(spec.ingress),
    )


def build_spec_from_raw(raw: Any, default: DockerBuildSpec | None) -> DockerBuildSpec | None:
    if raw is None:
        return clone_build_spec(default)
    if raw is False:
        return None
    if raw is True:
        return DockerBuildSpec(
            context=default.context if default is not None else ".",
            dockerfile=None if default is None else default.dockerfile,
        )
    if not isinstance(raw, Mapping):
        raise ValueError("build must be null, true, false, or an object")
    return DockerBuildSpec(
        context=str(raw.get("context", "." if default is None else default.context)),
        dockerfile=None
        if raw.get("dockerfile", None if default is None else default.dockerfile) is None
        else str(raw.get("dockerfile", None if default is None else default.dockerfile)),
    )


def service_spec_from_raw(
    raw: Mapping[str, Any] | None,
    default: ServiceSpec,
) -> ServiceSpec:
    base = clone_service_spec(default)
    if raw is None:
        return base
    return ServiceSpec(
        runner=str(raw.get("runner", base.runner)),
        replicas=int(raw.get("replicas", base.replicas)),
        command=normalize_command(raw.get("command", base.command)),
        env={**base.env, **normalize_str_map(raw.get("env"))},
        image=None if raw.get("image", base.image) is None else str(raw.get("image", base.image)),
        build=build_spec_from_raw(raw.get("build"), base.build),
        listen_port=None
        if raw.get("listen_port", base.listen_port) is None
        else int(raw.get("listen_port", base.listen_port)),
        ready_path=None
        if raw.get("ready_path", base.ready_path) is None
        else str(raw.get("ready_path", base.ready_path)),
        workdir=None if raw.get("workdir", base.workdir) is None else str(raw.get("workdir", base.workdir)),
        extra_args=normalize_command(raw.get("extra_args", base.extra_args)),
    )


def merge_stack_spec(raw: Any, default: WebhookStackSpec | None) -> WebhookStackSpec | None:
    if raw is None:
        return clone_stack_spec(default)
    if not isinstance(raw, Mapping):
        raise ValueError("stack must be an object")
    base = clone_stack_spec(default) or WebhookStackSpec(
        mode="webhook_multi_instance",
        webhook_path="/telegram/webhook",
        webhook_secret="loadtest-webhook-secret",
        app=ServiceSpec(
            runner="docker",
            replicas=1,
            command=["python", "-m", "app.main", "serve-webhook"],
            env={
                "BOT_WEBHOOK_ENABLED": "True",
                "BOT_FAKE_API_ENABLED": "True",
                "BOT_POLLING_ENABLED": "False",
                "TELEGRAM_WEBHOOK_HANDLE_IN_BACKGROUND": "False",
                "TELEGRAM_WEBHOOK_REQUIRE_HTTPS": "False",
                "TELEGRAM_WEBHOOK_URL": "http://loadtest.local",
                "TELEGRAM_WEBHOOK_SECRET": "loadtest-webhook-secret",
                "TELEGRAM_WEBHOOK_PATH": "/telegram/webhook",
                "SECURITY_STATE_BACKEND": "redis",
                "SECURITY_RATE_LIMIT_ENABLED": "True",
            },
            build=DockerBuildSpec(context="."),
            listen_port=8080,
            ready_path="/ready",
        ),
        worker=ServiceSpec(
            runner="docker",
            replicas=1,
            command=["python", "-m", "app.workers.run_outbox"],
            env={
                "SECURITY_STATE_BACKEND": "redis",
                "SECURITY_RATE_LIMIT_ENABLED": "True",
            },
            build=DockerBuildSpec(context="."),
        ),
        ingress=ServiceSpec(
            runner="process",
            replicas=1,
            command=[
                "{python}",
                "scripts/loadtest_ingress.py",
                "serve",
                "--listen-host",
                "127.0.0.1",
                "--listen-port",
                "{listen_port}",
                "--ingress-health-path",
                "/health",
                "--ready-path",
                "{app_ready_path}",
                "--webhook-path",
                "{webhook_path}",
                "--upstream-urls-json",
                "{app_replica_urls_json}",
            ],
            listen_port=9080,
            ready_path="/health",
        ),
    )
    shared_image = raw.get("image")
    shared_build = build_spec_from_raw(raw.get("build"), base.app.build or base.worker.build)
    app_default = clone_service_spec(base.app)
    worker_default = clone_service_spec(base.worker)
    if shared_image is not None:
        app_default.image = str(shared_image)
        worker_default.image = str(shared_image)
    if shared_build is not None:
        app_default.build = clone_build_spec(shared_build)
        worker_default.build = clone_build_spec(shared_build)
    app_default.replicas = int(raw.get("app_replicas", app_default.replicas))
    worker_default.replicas = int(raw.get("worker_replicas", worker_default.replicas))
    ingress_default = None if base.ingress is None else clone_service_spec(base.ingress)
    ingress_raw = raw.get("ingress")
    if ingress_raw is False:
        ingress = None
    elif isinstance(ingress_raw, Mapping):
        default_ingress = ingress_default or ServiceSpec(
            runner="process",
            replicas=1,
            command=[],
            listen_port=8081,
            ready_path="/health",
        )
        ingress = service_spec_from_raw(ingress_raw, default_ingress)
    else:
        ingress = ingress_default
    stack = WebhookStackSpec(
        mode=str(raw.get("mode", base.mode)),
        webhook_path=str(raw.get("webhook_path", base.webhook_path)),
        webhook_secret=str(raw.get("webhook_secret", base.webhook_secret)),
        app=service_spec_from_raw(raw.get("app"), app_default),
        worker=service_spec_from_raw(raw.get("worker"), worker_default),
        ingress=ingress,
    )
    stack.app.env.setdefault("BOT_WEBHOOK_ENABLED", "True")
    stack.app.env.setdefault("BOT_FAKE_API_ENABLED", "True")
    stack.app.env.setdefault("BOT_POLLING_ENABLED", "False")
    stack.app.env.setdefault("TELEGRAM_WEBHOOK_HANDLE_IN_BACKGROUND", "False")
    stack.app.env.setdefault("TELEGRAM_WEBHOOK_REQUIRE_HTTPS", "False")
    stack.app.env["TELEGRAM_WEBHOOK_URL"] = stack.app.env.get("TELEGRAM_WEBHOOK_URL", "http://loadtest.local")
    stack.app.env["TELEGRAM_WEBHOOK_SECRET"] = stack.webhook_secret
    stack.app.env["TELEGRAM_WEBHOOK_PATH"] = stack.webhook_path
    stack.app.env.setdefault("DB_APP_REPLICA_COUNT", str(stack.app.replicas))
    stack.app.env.setdefault("DB_WORKER_REPLICA_COUNT", str(stack.worker.replicas))
    stack.app.env.setdefault("SECURITY_STATE_BACKEND", "redis")
    stack.app.env.setdefault("SECURITY_RATE_LIMIT_ENABLED", "True")
    stack.worker.env.setdefault("DB_APP_REPLICA_COUNT", str(stack.app.replicas))
    stack.worker.env.setdefault("DB_WORKER_REPLICA_COUNT", str(stack.worker.replicas))
    stack.worker.env.setdefault("SECURITY_STATE_BACKEND", "redis")
    stack.worker.env.setdefault("SECURITY_RATE_LIMIT_ENABLED", "True")
    return stack


def merge_pgbouncer(
    raw_value: Any,
    default_value: Mapping[str, str] | None,
) -> dict[str, str] | None:
    if raw_value is False:
        return None
    if raw_value is None:
        return None if default_value is None else dict(default_value)
    if raw_value is True:
        return dict(default_value or {})
    if isinstance(raw_value, Mapping):
        merged = dict(default_value or {})
        merged.update(normalize_str_map(raw_value))
        return merged
    raise ValueError("pgbouncer must be false, true, null, or an object")


def sanitize_database_name(name: str) -> str:
    return sanitize_name(name).replace("-", "_")[:50] or "deutsch_trainer_load"


def build_runtime_spec(
    raw: Mapping[str, Any],
    defaults: BuildDefaults,
) -> RuntimeSpec:
    name = str(raw["name"])
    role = str(raw.get("role", "candidate"))
    env = {**defaults.default_env, **normalize_str_map(raw.get("env"))}
    if raw.get("measurements"):
        measurements = build_custom_measurements(raw["measurements"])
    else:
        measurements = list(defaults.default_measurements)
    prepare = list(defaults.default_prepare)
    prepare.extend(build_custom_measurements(raw.get("prepare", [])))
    postgres_db = str(raw.get("postgres_db", sanitize_database_name(name)))
    backend = env.get("DB_CONNECTION_BACKEND", "")
    if raw.get("pgbouncer") is None and backend == "direct":
        pgbouncer = None
    else:
        pgbouncer = merge_pgbouncer(raw.get("pgbouncer"), defaults.default_pgbouncer)
    context = {**defaults.default_context, **normalize_str_map(raw.get("context"))}
    stack = merge_stack_spec(raw.get("stack"), defaults.default_stack)
    seed_session_count = _seed_session_count(
        prepare,
        measurements,
        override=raw.get("seed_session_count"),
    )
    context["seed_session_count"] = str(seed_session_count)
    return RuntimeSpec(
        name=name,
        role=role,
        env=env,
        context=context,
        prepare=prepare,
        measurements=measurements,
        postgres_settings={
            **defaults.default_postgres_settings,
            **normalize_str_map(raw.get("postgres_settings")),
        },
        redis_args=normalize_str_list(raw.get("redis_args")) or list(defaults.default_redis_args),
        pgbouncer=pgbouncer,
        postgres_image=str(raw.get("postgres_image", defaults.top_level_images["postgres_image"])),
        redis_image=str(raw.get("redis_image", defaults.top_level_images["redis_image"])),
        pgbouncer_image=str(raw.get("pgbouncer_image", defaults.top_level_images["pgbouncer_image"])),
        postgres_user=str(raw.get("postgres_user", defaults.top_level_runtime["postgres_user"])),
        postgres_password=str(raw.get("postgres_password", defaults.top_level_runtime["postgres_password"])),
        postgres_db=postgres_db,
        postgres_shm_size=str(raw.get("postgres_shm_size", defaults.top_level_runtime["postgres_shm_size"])),
        ready_timeout_seconds=float(
            raw.get("ready_timeout_seconds", defaults.top_level_runtime["ready_timeout_seconds"])
        ),
        stack=stack,
    )


def _seed_session_count(
    prepare: Sequence[CommandSpec],
    measurements: Sequence[CommandSpec],
    *,
    override: Any,
) -> int:
    if override is not None:
        return int(override)
    required = 0
    for command in [*prepare, *measurements]:
        required = max(required, _required_sessions_for_command(command))
    return max(required, 5_000)


def _required_sessions_for_command(command: CommandSpec) -> int:
    uses_worker_pipeline = any(item.endswith("worker_pipeline_v2_regression_isolation.py") for item in command.command)
    uses_webhook_load = "webhook-load" in command.command
    if not ((uses_worker_pipeline and "run" in command.command) or uses_webhook_load):
        return 0
    total_requests = _command_context_int(command, "total_requests")
    session_offset = _command_context_int(command, "session_offset")
    return session_offset + total_requests


def _command_context_int(command: CommandSpec, key: str) -> int:
    value = command.context.get(key, "0")
    return int(value)


def phase1_variants(spec: Mapping[str, Any]) -> list[RuntimeSpec]:
    raw_variants = spec.get("variants")
    if not isinstance(raw_variants, list) or not raw_variants:
        raise ValueError("phase1 requires a non-empty variants array")
    defaults = BuildDefaults(
        default_env=normalize_str_map(spec.get("env")),
        default_context={},
        default_postgres_settings=normalize_str_map(spec.get("postgres_settings")),
        default_redis_args=normalize_str_list(spec.get("redis_args")),
        default_pgbouncer=None,
        default_prepare=[],
        default_measurements=[default_phase1_measurement(spec)],
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
    return [build_runtime_spec(raw, defaults) for raw in raw_variants]


def phase2_variants(spec: Mapping[str, Any]) -> list[RuntimeSpec]:
    top_level_pgbouncer = {
        "pool_mode": "transaction",
        "max_client_conn": str(spec.get("pgbouncer_max_client_conn", 200)),
        "default_pool_size": str(spec.get("pgbouncer_default_pool_size", 20)),
        "reserve_pool_size": str(spec.get("pgbouncer_reserve_pool_size", 5)),
        "ignore_startup_parameters": "extra_float_digits",
        "server_reset_query": "DISCARD ALL",
    }
    raw_variants = spec.get("variants")
    if raw_variants is None:
        base_env = normalize_str_map(spec.get("env"))
        measurements = [asdict(measurement) for measurement in default_phase2_measurements(spec)]
        seed = asdict(default_worker_seed_command())
        raw_variants = [
            {
                "name": str(spec.get("baseline_name", "direct")),
                "role": "baseline",
                "env": {**base_env, "DB_CONNECTION_BACKEND": "direct"},
                "pgbouncer": False,
                "measurements": measurements,
            },
            {
                "name": str(spec.get("candidate_name", "pgbouncer")),
                "role": "candidate",
                "env": {**base_env, "DB_CONNECTION_BACKEND": "pgbouncer_transaction"},
                "pgbouncer": spec.get("pgbouncer", top_level_pgbouncer),
                "measurements": measurements,
            },
        ]
    if not isinstance(raw_variants, list) or not raw_variants:
        raise ValueError("phase2 requires at least one variant")
    defaults = BuildDefaults(
        default_env=normalize_str_map(spec.get("env")),
        default_context={},
        default_postgres_settings=normalize_str_map(spec.get("postgres_settings")),
        default_redis_args=normalize_str_list(spec.get("redis_args")),
        default_pgbouncer=top_level_pgbouncer,
        default_prepare=_phase2_prepare(bool_setting(spec.get("migrate"), True)),
        default_measurements=default_phase2_measurements(spec),
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
    return [build_runtime_spec(raw, defaults) for raw in raw_variants]


def _phase2_prepare(include_migration: bool) -> list[CommandSpec]:
    prepare = [default_worker_seed_command()]
    if include_migration:
        prepare.insert(0, default_migrate_command())
    return prepare


def _phase4_webhook_plan_command(
    plan: Mapping[str, Any],
    *,
    runtime: RuntimeSpec,
    session_offset: int,
) -> tuple[CommandSpec, bool]:
    assert runtime.stack is not None
    mode = str(plan.get("mode", "steady")).strip().lower()
    total_requests = str(plan.get("total_requests", 500))
    burst_interval_seconds = float(plan.get("burst_interval_seconds", 5.0))
    target_rps = str(plan.get("target_rps", max(1, round(int(total_requests) / burst_interval_seconds))))
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
    if mode == "burst":
        context["burst_window_seconds"] = str(plan.get("burst_window_seconds", 1.0))
        context["burst_interval_seconds"] = str(burst_interval_seconds)
        command.extend(
            [
                "--burst-window-seconds",
                "{burst_window_seconds}",
                "--burst-interval-seconds",
                "{burst_interval_seconds}",
            ]
        )
    env: dict[str, str] = {}
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
    return (
        CommandSpec(
            name=str(plan.get("name", f"{mode}_{total_requests}_requests")),
            command=command,
            parser="json",
            env=env,
            context=context,
            compare_paths=normalize_str_list(plan.get("compare_paths")) or list(PHASE4_WEBHOOK_COMPARE_PATHS),
        ),
        True,
    )


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
        default_prepare=[default_migrate_command()] if bool_setting(spec.get("migrate"), True) else [],
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


def execute_runtime(runtime: RuntimeSpec, *, keep_runtime: bool) -> dict[str, Any]:
    runner = DockerRuntime(runtime, keep_running=keep_runtime)
    record: dict[str, Any] = {
        "name": runtime.name,
        "role": runtime.role,
        "status": "running",
        "prepare": {},
        "measurements": {},
    }
    try:
        runner.start()
        record["runtime"] = runner.describe()
        base_env = runner.base_env()
        base_context = runner.context()
        before_stack = [command for command in runtime.prepare if command.stage == "before_stack"]
        after_stack = [command for command in runtime.prepare if command.stage == "after_stack"]
        for command in before_stack:
            result = run_command_spec(command, base_env=base_env, base_context=base_context)
            record["prepare"][command.name] = result
            if not result["ok"] and not command.allow_failure:
                raise RuntimeError(f"prepare command failed: {command.name}")
        runner.start_stack()
        record["runtime"] = runner.describe()
        base_context = runner.context()
        for command in after_stack:
            result = run_command_spec(command, base_env=base_env, base_context=base_context)
            record["prepare"][command.name] = result
            if not result["ok"] and not command.allow_failure:
                raise RuntimeError(f"prepare command failed: {command.name}")
        for command in runtime.measurements:
            result = run_command_spec(command, base_env=base_env, base_context=base_context)
            record["measurements"][command.name] = result
            if not result["ok"] and not command.allow_failure:
                raise RuntimeError(f"measurement command failed: {command.name}")
        record["status"] = "passed"
        return record
    except Exception as exc:  # noqa: BLE001
        record["status"] = "failed"
        record["error"] = f"{exc.__class__.__name__}: {exc}"
        if "runtime" not in record:
            record["runtime"] = runner.describe()
        return record
    finally:
        if runner.started:
            record["container_logs"] = runner.collect_logs()
        runner.stop()
        record["runtime"] = runner.describe()


def phase_report(phase: str, variants: Sequence[RuntimeSpec], *, keep_runtime: bool) -> tuple[dict[str, Any], bool]:
    baseline_variant = next((variant.name for variant in variants if variant.role == "baseline"), None)
    report: dict[str, Any] = {
        "generated_at_utc": now_utc(),
        "phase": phase,
        "repo_state": gather_repo_state(),
        "docker_version": gather_docker_version(),
        "baseline_variant": baseline_variant,
        "variants": [],
    }
    failed = False
    for runtime in variants:
        result = execute_runtime(runtime, keep_runtime=keep_runtime)
        report["variants"].append(result)
        if result["status"] != "passed":
            failed = True
    report["comparisons"] = build_comparisons(report["variants"])
    report["status"] = "failed" if failed else "passed"
    return report, failed


def run_phase(args: argparse.Namespace, phase: str) -> int:
    spec = load_spec(args.spec_file, args.spec_json)
    if phase == "phase1":
        variants = phase1_variants(spec)
    elif phase == "phase2":
        variants = phase2_variants(spec)
    elif phase == "phase4":
        variants = phase4_variants(spec)
    else:
        raise ValueError(f"Unsupported phase: {phase}")
    report, failed = phase_report(phase, variants, keep_runtime=args.keep_runtime)
    report["phase_spec"] = spec
    evidence_path = resolve_evidence_path(args.evidence_file)
    write_json(evidence_path, report)
    print(f"load stabilization evidence written: {evidence_path}")
    return 1 if failed else 0


def _percentile(values: Sequence[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * percentile)))
    return round(ordered[index], 3)


def _summarize_numeric(values: Sequence[float]) -> dict[str, float]:
    if not values:
        return {"count": 0, "p50": 0.0, "p95": 0.0, "p99": 0.0, "max": 0.0}
    return {
        "count": float(len(values)),
        "p50": _percentile(values, 0.50),
        "p95": _percentile(values, 0.95),
        "p99": _percentile(values, 0.99),
        "max": round(max(values), 3),
    }


def _scheduled_offset(index: int, *, target_rps: float, mode: str, burst_window: float, burst_interval: float) -> float:
    nominal_offset = index / target_rps
    if mode == "steady":
        return nominal_offset
    interval_index = math.floor(nominal_offset / burst_interval)
    interval_started = interval_index * burst_interval
    interval_offset = nominal_offset - interval_started
    return interval_started + (interval_offset * (burst_window / burst_interval))


def _measurement_session_id(session_offset: int, request_index: int) -> int:
    return session_offset + request_index + 1


def _build_answer_callback_update(
    update_id: int,
    *,
    session_id: int,
    telegram_user_id: int,
    selected_option_id: str,
) -> dict[str, Any]:
    question_token = f"tok{session_id:08d}"
    return {
        "update_id": update_id,
        "callback_query": {
            "id": f"cbq-{update_id}",
            "from": {
                "id": telegram_user_id,
                "is_bot": False,
                "first_name": "Load",
            },
            "chat_instance": f"chat-{session_id}",
            "message": {
                "message_id": update_id,
                "date": 1_720_000_000,
                "chat": {"id": telegram_user_id, "type": "private"},
                "from": {
                    "id": LOADTEST_BOT_USER_ID,
                    "is_bot": True,
                    "first_name": "LoadTestBot",
                    "username": "dtb_loadtest_bot",
                },
                "text": "load-harness-question",
            },
            "data": (
                f"{CALLBACK_TRAIN_ANSWER_PREFIX}:"
                f"{session_id}:{question_token}:{selected_option_id}"
            ),
        },
    }


async def _sample_pgbouncer_until(
    stop_event: asyncio.Event,
    *,
    output_path: str,
    interval_ms: float,
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
            pools = await _run_pgbouncer_show("SHOW POOLS;")
            stats = await _run_pgbouncer_show("SHOW STATS;")
            if not config_rows:
                config_rows = await _run_pgbouncer_show("SHOW CONFIG;")
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
    write_json(resolve_evidence_path(output_path), payload)
    return payload["summary"]


async def _run_pgbouncer_show(sql: str) -> list[dict[str, str]]:
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
    )
    stdout, stderr = await process.communicate()
    if process.returncode != 0:
        message = stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(message or f"psql failed for {sql.strip()}")
    return _parse_csv_rows(stdout.decode("utf-8", errors="replace"))


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


async def webhook_load(args: argparse.Namespace) -> int:
    base_url = args.base_url.rstrip("/")
    webhook_url = f"{base_url}{args.webhook_path}"
    if args.arrival_mode == "burst" and args.burst_window_seconds > args.burst_interval_seconds:
        raise SystemExit("--burst-window-seconds must be less than or equal to --burst-interval-seconds")
    if args.session_offset < 0:
        raise SystemExit("--session-offset must be greater than or equal to 0")
    if args.seeded_session_count <= 0:
        raise SystemExit("--seeded-session-count must be greater than 0")
    required_sessions = args.session_offset + args.total_requests
    if required_sessions > args.seeded_session_count:
        raise SystemExit("configured session selection exceeds seeded session capacity")

    timeout = httpx.Timeout(args.timeout_seconds)
    limits = httpx.Limits(max_connections=args.concurrency, max_keepalive_connections=args.concurrency)
    latencies_ms: list[float] = []
    dispatch_lag_ms: list[float] = []
    statuses: Counter[int] = Counter()
    errors: Counter[str] = Counter()
    semaphore = asyncio.Semaphore(args.concurrency)
    in_flight = 0
    max_in_flight = 0
    lock = asyncio.Lock()
    started_at = perf_counter()
    pgbouncer_stop_event = asyncio.Event()
    pgbouncer_task: asyncio.Task[dict[str, Any]] | None = None
    pgbouncer_summary: dict[str, Any] | None = None

    if args.pgbouncer_sample_output:
        pgbouncer_task = asyncio.create_task(
            _sample_pgbouncer_until(
                pgbouncer_stop_event,
                output_path=args.pgbouncer_sample_output,
                interval_ms=args.pgbouncer_sample_interval_ms,
            )
        )

    try:
        async with httpx.AsyncClient(timeout=timeout, limits=limits) as client:
            async def invoke(index: int) -> None:
                nonlocal in_flight, max_in_flight
                scheduled_at = _scheduled_offset(
                    index,
                    target_rps=args.target_rps,
                    mode=args.arrival_mode,
                    burst_window=args.burst_window_seconds,
                    burst_interval=args.burst_interval_seconds,
                )
                now_offset = perf_counter() - started_at
                if scheduled_at > now_offset:
                    await asyncio.sleep(scheduled_at - now_offset)
                dispatch_started = perf_counter()
                dispatch_lag_ms.append(round((dispatch_started - started_at - scheduled_at) * 1000, 3))
                async with semaphore:
                    async with lock:
                        in_flight += 1
                        max_in_flight = max(max_in_flight, in_flight)
                    request_started = perf_counter()
                    try:
                        session_id = _measurement_session_id(args.session_offset, index)
                        response = await client.post(
                            webhook_url,
                            headers={
                                "Content-Type": "application/json",
                                "X-Telegram-Bot-Api-Secret-Token": args.secret_token,
                            },
                            json=_build_answer_callback_update(
                                args.start_update_id + index,
                                session_id=session_id,
                                telegram_user_id=args.base_user_id + session_id,
                                selected_option_id=args.selected_option_id,
                            ),
                        )
                        statuses[response.status_code] += 1
                    except Exception as exc:  # noqa: BLE001
                        errors[exc.__class__.__name__] += 1
                    else:
                        latencies_ms.append(round((perf_counter() - request_started) * 1000, 3))
                    finally:
                        async with lock:
                            in_flight -= 1

            await asyncio.gather(*(invoke(index) for index in range(args.total_requests)))
    finally:
        if pgbouncer_task is not None:
            pgbouncer_stop_event.set()
            pgbouncer_summary = await pgbouncer_task

    elapsed = perf_counter() - started_at
    accepted = sum(count for status, count in statuses.items() if 200 <= status < 300)
    error_total = args.total_requests - accepted
    latency_summary = _summarize_numeric(latencies_ms)
    result = {
        "requests": {
            "requested": args.total_requests,
            "accepted": accepted,
            "errors": error_total,
            "success_rate": round(accepted / args.total_requests, 6) if args.total_requests else 0.0,
            "status_counts": {str(status): count for status, count in sorted(statuses.items())},
            "error_types": dict(errors),
        },
        "arrival": {
            "mode": args.arrival_mode,
            "burst_window_seconds": None if args.arrival_mode == "steady" else args.burst_window_seconds,
            "burst_interval_seconds": None if args.arrival_mode == "steady" else args.burst_interval_seconds,
            "scheduled_dispatch_span_sec": round(
                _scheduled_offset(
                    max(args.total_requests - 1, 0),
                    target_rps=args.target_rps,
                    mode=args.arrival_mode,
                    burst_window=args.burst_window_seconds,
                    burst_interval=args.burst_interval_seconds,
                ),
                3,
            ),
        },
        "latency_ms": latency_summary,
        "answer_p95_ms": latency_summary["p95"],
        "dispatch_lag_ms": _summarize_numeric(dispatch_lag_ms),
        "harness_validation": {
            "open_loop_target_rps": args.target_rps,
            "arrival_mode": args.arrival_mode,
            "achieved_rps": round(args.total_requests / max(elapsed, 0.001), 3),
            "max_in_flight_requests": max_in_flight,
        },
    }
    if pgbouncer_summary is not None:
        result["pgbouncer_admin_sampling"] = pgbouncer_summary
    print(json.dumps(result, indent=2, ensure_ascii=True))
    return 0 if error_total == 0 else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Disposable docker orchestration for load-stabilization evidence.")
    parser.add_argument(
        "--keep-runtime",
        action="store_true",
        help="Leave disposable docker resources running after the phase finishes.",
    )
    subparsers = parser.add_subparsers(dest="phase", required=True)

    phase1 = subparsers.add_parser("phase1", help="Run PostgreSQL tuning variants.")
    add_spec_args(phase1)
    phase1.add_argument("--evidence-file", required=True, help="Repo-local qa_evidence JSON path.")
    phase1.set_defaults(func=lambda args: run_phase(args, "phase1"))

    phase2 = subparsers.add_parser("phase2", help="Run direct-vs-PgBouncer comparisons.")
    add_spec_args(phase2)
    phase2.add_argument("--evidence-file", required=True, help="Repo-local qa_evidence JSON path.")
    phase2.set_defaults(func=lambda args: run_phase(args, "phase2"))

    phase4 = subparsers.add_parser("phase4", help="Run steady/burst plan-driven load evidence.")
    add_spec_args(phase4)
    phase4.add_argument("--evidence-file", required=True, help="Repo-local qa_evidence JSON path.")
    phase4.set_defaults(func=lambda args: run_phase(args, "phase4"))

    webhook_load_parser = subparsers.add_parser(
        "webhook-load",
        help="Send disposable webhook load directly at the local ingress/runtime path.",
    )
    webhook_load_parser.add_argument("--base-url", required=True)
    webhook_load_parser.add_argument("--webhook-path", required=True)
    webhook_load_parser.add_argument("--secret-token", required=True)
    webhook_load_parser.add_argument("--target-rps", type=float, required=True)
    webhook_load_parser.add_argument("--total-requests", type=int, required=True)
    webhook_load_parser.add_argument("--session-offset", type=int, default=0)
    webhook_load_parser.add_argument("--seeded-session-count", type=int, default=5000)
    webhook_load_parser.add_argument("--selected-option-id", default="a1")
    webhook_load_parser.add_argument("--concurrency", type=int, default=100)
    webhook_load_parser.add_argument("--arrival-mode", choices=["steady", "burst"], default="steady")
    webhook_load_parser.add_argument("--burst-window-seconds", type=float, default=1.0)
    webhook_load_parser.add_argument("--burst-interval-seconds", type=float, default=5.0)
    webhook_load_parser.add_argument("--timeout-seconds", type=float, default=10.0)
    webhook_load_parser.add_argument("--start-update-id", type=int, default=1_000_000)
    webhook_load_parser.add_argument("--base-user-id", type=int, default=7_000_000_000)
    webhook_load_parser.add_argument("--pgbouncer-sample-output")
    webhook_load_parser.add_argument("--pgbouncer-sample-interval-ms", type=float, default=250.0)
    webhook_load_parser.set_defaults(func=webhook_load)
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    result = args.func(args)
    if asyncio.iscoroutine(result):
        result = asyncio.run(result)
    raise SystemExit(result)


if __name__ == "__main__":
    main()
