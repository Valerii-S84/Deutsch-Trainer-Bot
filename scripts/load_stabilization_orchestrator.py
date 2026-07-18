from __future__ import annotations

import argparse
import asyncio
import csv
from collections import Counter
import json
import math
import os
import signal
import sys
import time
from io import StringIO
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from time import perf_counter
from typing import Any

import asyncpg
from aiohttp import ClientError, ClientSession, ClientTimeout, TCPConnector
from redis.asyncio import Redis
from redis.exceptions import RedisError, ResponseError

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
    "acceptance.passed",
    "event_validation.passed",
    "queue_processing.lag_ms.p95",
    "harness_validation.achieved_rps",
]
CALLBACK_TRAIN_ANSWER_PREFIX = "train:ans"
LOADTEST_BOT_USER_ID = 123456789
DEFAULT_SAMPLER_QUERY_TIMEOUT_SECONDS = 5.0
DEFAULT_SAMPLER_STOP_TIMEOUT_SECONDS = 15.0


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
    timeout_raw = raw.get("timeout_seconds")
    return CommandSpec(
        name=str(raw["name"]),
        command=normalize_command(raw["command"]),
        parser=str(raw.get("parser", "text")),
        env=normalize_str_map(raw.get("env")),
        context=normalize_str_map(raw.get("context")),
        compare_paths=normalize_str_list(raw.get("compare_paths")),
        allow_failure=bool_setting(raw.get("allow_failure"), False),
        stage=stage_setting(raw.get("stage")),
        timeout_seconds=None if timeout_raw in (None, "") else float(timeout_raw),
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


from scripts.load_stabilization_specs import (
    clone_build_spec,
    clone_service_spec,
    clone_stack_spec,
    build_spec_from_raw,
    service_spec_from_raw,
    merge_stack_spec,
    merge_pgbouncer,
    sanitize_database_name,
    build_runtime_spec,
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


from scripts.load_stabilization_phase4 import (
    _phase2_prepare,
    _phase4_webhook_plan_command,
    _phase4_webhook_measurement_timeout,
    phase4_plan_command,
    phase4_variants,
)
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


from scripts.load_stabilization_webhook_payloads import (
    _percentile,
    _summarize_numeric,
    _scheduled_offset,
    _measurement_session_id,
    _build_answer_callback_update,
)
from scripts.load_stabilization_postgres_metrics import (
    _sample_postgres_lock_profile_until,
    _connect_postgres_lock_sampler,
    _normalize_asyncpg_dsn,
    _validate_webhook_processing,
    _queue_drained,
    _fetch_webhook_db_validation,
    _fetch_webhook_queue_validation,
    _redis_stream_group_backlog,
    _fetch_rows,
    _fetch_rows_with_timeout,
    _summarize_postgres_lock_samples,
    _postgres_sample_counts,
    _counter_rows,
    _compact_postgres_sample,
    _none_label,
)
from scripts.load_stabilization_pgbouncer_metrics import (
    _sample_pgbouncer_until,
    _finish_sampler_task,
    _sampler_task_result,
    _write_sampler_failure_marker,
    _run_pgbouncer_show,
    _communicate_sampler_process,
    _signal_async_process_tree,
    _required_env,
    _parse_csv_rows,
    _pgbouncer_config_map,
    _summarize_pgbouncer_samples,
    _max_row_value,
    _number_or_zero,
    _webhook_acceptance,
)
from scripts.load_stabilization_webhook_load import (
    webhook_load,
    _webhook_load_sharded,
    _run_webhook_load_shard,
    _shard_size,
    _shard_offset,
    _warmup_http_connections,
)
from scripts.load_stabilization_cli import build_parser, main

def _install_uvloop_if_available() -> None:
    try:
        import uvloop
    except ImportError:
        return
    uvloop.install()


if __name__ == "__main__":
    main()
