from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import signal
import subprocess
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
QA_EVIDENCE_DIR = ROOT / "qa_evidence"
DEFAULT_POSTGRES_IMAGE = os.environ.get("DTB_LOAD_POSTGRES_IMAGE", "postgres:16-alpine")
DEFAULT_REDIS_IMAGE = os.environ.get("DTB_LOAD_REDIS_IMAGE", "redis:7-alpine")
DEFAULT_PGBOUNCER_IMAGE = os.environ.get("DTB_LOAD_PGBOUNCER_IMAGE", "edoburu/pgbouncer:latest")
URL_PATTERNS = (
    re.compile(r"postgresql(?:\+asyncpg)?://[^\s'\"\)]+"),
    re.compile(r"redis://[^\s'\"\)]+"),
)


@dataclass(slots=True)
class CommandSpec:
    name: str
    command: list[str]
    parser: str = "text"
    env: dict[str, str] = field(default_factory=dict)
    context: dict[str, str] = field(default_factory=dict)
    compare_paths: list[str] = field(default_factory=list)
    allow_failure: bool = False
    stage: str = "before_stack"
    timeout_seconds: float | None = None


@dataclass(slots=True)
class DockerBuildSpec:
    context: str = "."
    dockerfile: str | None = None


@dataclass(slots=True)
class ServiceSpec:
    runner: str
    replicas: int
    command: list[str]
    env: dict[str, str] = field(default_factory=dict)
    image: str | None = None
    build: DockerBuildSpec | None = None
    listen_port: int | None = None
    ready_path: str | None = None
    workdir: str | None = None
    extra_args: list[str] = field(default_factory=list)


@dataclass(slots=True)
class WebhookStackSpec:
    mode: str
    webhook_path: str
    webhook_secret: str
    app: ServiceSpec
    worker: ServiceSpec
    answer_worker: ServiceSpec | None = None
    outbox_worker: ServiceSpec | None = None
    ingress: ServiceSpec | None = None


@dataclass(slots=True)
class RuntimeSpec:
    name: str
    role: str
    env: dict[str, str]
    context: dict[str, str]
    prepare: list[CommandSpec]
    measurements: list[CommandSpec]
    postgres_settings: dict[str, str] = field(default_factory=dict)
    redis_args: list[str] = field(default_factory=list)
    pgbouncer: dict[str, str] | None = None
    postgres_image: str = DEFAULT_POSTGRES_IMAGE
    redis_image: str = DEFAULT_REDIS_IMAGE
    pgbouncer_image: str = DEFAULT_PGBOUNCER_IMAGE
    postgres_user: str = "postgres"
    postgres_password: str = "postgres"
    postgres_db: str = "deutsch_trainer_load"
    postgres_shm_size: str = "128m"
    ready_timeout_seconds: float = 60.0
    stack: WebhookStackSpec | None = None


@dataclass(slots=True)
class ProcessResult:
    argv: list[str]
    returncode: int
    stdout: str
    stderr: str
    duration_seconds: float
    timed_out: bool = False
    timeout_seconds: float | None = None


def now_utc() -> str:
    return datetime.now(UTC).isoformat()


def sanitize_name(value: str) -> str:
    safe = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return safe[:40] or "variant"


def normalize_str_map(raw: Mapping[str, Any] | None) -> dict[str, str]:
    if not raw:
        return {}
    return {str(key): str(value) for key, value in raw.items()}


def normalize_str_list(raw: Sequence[Any] | None) -> list[str]:
    if not raw:
        return []
    return [str(item) for item in raw]


def normalize_command(raw: Sequence[Any] | str) -> list[str]:
    if isinstance(raw, str):
        return shlex.split(raw)
    return [str(item) for item in raw]


def resolve_evidence_path(raw_path: str) -> Path:
    path = (ROOT / raw_path).resolve()
    qa_root = QA_EVIDENCE_DIR.resolve()
    if path != qa_root and qa_root not in path.parents:
        raise ValueError("evidence file must stay under qa_evidence/")
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


def scrub_output(text: str) -> str:
    cleaned = text
    for pattern in URL_PATTERNS:
        cleaned = pattern.sub("<redacted-url>", cleaned)
    return cleaned


def display_command(argv: Sequence[str]) -> str:
    return " ".join(shlex.quote(item) for item in argv)


def excerpt(text: str, *, max_lines: int = 12, max_chars: int = 1200) -> list[str]:
    lines = [line for line in text.strip().splitlines() if line.strip()]
    if len(lines) > max_lines:
        head = max_lines // 2
        tail = max_lines - head
        lines = [*lines[:head], "...", *lines[-tail:]]
    return [line[:max_chars] for line in lines]


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def maybe_number(raw: str) -> int | float | str:
    lowered = raw.lower()
    if lowered in {"true", "false"}:
        return lowered == "true"
    try:
        return int(raw)
    except ValueError:
        try:
            return float(raw)
        except ValueError:
            return raw


def parse_json_stdout(stdout: str) -> Any:
    lines = stdout.splitlines()
    for index, line in enumerate(lines):
        stripped = line.lstrip()
        if stripped.startswith("{") or stripped.startswith("["):
            return json.loads("\n".join(lines[index:]))
    return json.loads(stdout)


def parse_metric_line(stdout: str) -> dict[str, Any]:
    lines = [line.strip() for line in stdout.splitlines() if line.strip()]
    if not lines:
        raise ValueError("metric output is empty")
    parts = lines[-1].split()
    if not parts:
        raise ValueError("metric output is empty")
    parsed: dict[str, Any] = {"metric": parts[0]}
    for token in parts[1:]:
        if "=" not in token:
            continue
        key, raw_value = token.split("=", 1)
        parsed[key] = maybe_number(raw_value)
    return parsed


def parse_stdout(stdout: str, parser: str) -> Any:
    if parser == "text":
        return {"text": stdout.strip()}
    if parser == "json":
        return parse_json_stdout(stdout)
    if parser == "metric_line":
        return parse_metric_line(stdout)
    raise ValueError(f"Unsupported parser: {parser}")


def format_template(value: str, context: Mapping[str, str]) -> str:
    return value.format_map(dict(context))


def run_process(
    argv: Sequence[str],
    *,
    env: Mapping[str, str] | None = None,
    cwd: Path = ROOT,
    timeout_seconds: float | None = None,
) -> ProcessResult:
    started = time.perf_counter()
    process = subprocess.Popen(  # noqa: S603
        list(argv),
        cwd=str(cwd),
        env=dict(env) if env is not None else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    timed_out = False
    try:
        stdout, stderr = process.communicate(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        timed_out = True
        _signal_process_tree(process, signal.SIGTERM)
        try:
            stdout, stderr = process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            _signal_process_tree(process, signal.SIGKILL)
            stdout, stderr = process.communicate(timeout=5)
    return ProcessResult(
        argv=list(argv),
        returncode=process.returncode if process.returncode is not None else -9,
        stdout=scrub_output(stdout or ""),
        stderr=scrub_output(stderr or ""),
        duration_seconds=round(time.perf_counter() - started, 3),
        timed_out=timed_out,
        timeout_seconds=timeout_seconds,
    )


def build_command_record(result: ProcessResult, *, parser: str, parsed: Any = None, parse_error: str | None = None) -> dict[str, Any]:
    return {
        "command": display_command(result.argv),
        "parser": parser,
        "returncode": result.returncode,
        "ok": result.returncode == 0 and parse_error is None,
        "timed_out": result.timed_out,
        "timeout_seconds": result.timeout_seconds,
        "duration_seconds": result.duration_seconds,
        "stdout_sha256": sha256_text(result.stdout),
        "stderr_sha256": sha256_text(result.stderr),
        "stdout_excerpt": excerpt(result.stdout),
        "stderr_excerpt": excerpt(result.stderr),
        "parsed": parsed,
        "parse_error": parse_error,
    }


def run_command_spec(
    spec: CommandSpec,
    *,
    base_env: Mapping[str, str],
    base_context: Mapping[str, str],
    cwd: Path = ROOT,
) -> dict[str, Any]:
    context = dict(base_context)
    context.update(spec.context)
    argv = [format_template(arg, context) for arg in spec.command]
    env = dict(base_env)
    env.update({key: format_template(value, context) for key, value in spec.env.items()})
    result = run_process(argv, env=env, cwd=cwd, timeout_seconds=spec.timeout_seconds)
    parsed: Any = None
    parse_error: str | None = None
    try:
        parsed = parse_stdout(result.stdout, spec.parser)
    except Exception as exc:  # noqa: BLE001
        parse_error = f"{exc.__class__.__name__}: {exc}"
    record = build_command_record(result, parser=spec.parser, parsed=parsed, parse_error=parse_error)
    record["name"] = spec.name
    record["compare_paths"] = list(spec.compare_paths)
    return record


def _signal_process_tree(process: subprocess.Popen[str], sig: int) -> None:
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, sig)
    except (OSError, ProcessLookupError):
        try:
            process.send_signal(sig)
        except (OSError, ProcessLookupError):
            return


def get_nested_value(payload: Any, path: str) -> int | float | None:
    current = payload
    for part in path.split("."):
        if not isinstance(current, Mapping) or part not in current:
            return None
        current = current[part]
    if isinstance(current, bool):
        return int(current)
    if isinstance(current, (int, float)):
        return float(current)
    return None


def build_comparisons(variants: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    baseline = next((variant for variant in variants if variant.get("role") == "baseline"), None)
    if baseline is None:
        return []
    baseline_name = str(baseline["name"])
    baseline_measurements = baseline.get("measurements", {})
    comparisons = []
    for candidate in variants:
        if candidate is baseline:
            continue
        measurement_deltas = _candidate_measurement_deltas(candidate, baseline_measurements)
        if not measurement_deltas:
            continue
        comparisons.append(
            {
                "baseline_variant": baseline_name,
                "candidate_variant": str(candidate["name"]),
                "measurements": measurement_deltas,
            }
        )
    return comparisons


def _candidate_measurement_deltas(
    candidate: Mapping[str, Any],
    baseline_measurements: Mapping[str, Any],
) -> dict[str, Any]:
    deltas: dict[str, Any] = {}
    for name, measurement in candidate.get("measurements", {}).items():
        baseline_measurement = baseline_measurements.get(name)
        metrics = _measurement_metric_deltas(measurement, baseline_measurement)
        if metrics:
            deltas[name] = metrics
    return deltas


def _measurement_metric_deltas(
    candidate_measurement: Mapping[str, Any],
    baseline_measurement: Mapping[str, Any] | None,
) -> dict[str, Any]:
    if not baseline_measurement:
        return {}
    candidate_payload = candidate_measurement.get("parsed")
    baseline_payload = baseline_measurement.get("parsed")
    if not candidate_payload or not baseline_payload:
        return {}

    metrics: dict[str, Any] = {}
    for path in candidate_measurement.get("compare_paths", []):
        delta = _metric_delta(path, baseline_payload, candidate_payload)
        if delta is not None:
            metrics[path] = delta
    return metrics


def _metric_delta(path: str, baseline_payload: Any, candidate_payload: Any) -> dict[str, float] | None:
    baseline_value = get_nested_value(baseline_payload, path)
    candidate_value = get_nested_value(candidate_payload, path)
    if baseline_value is None or candidate_value is None:
        return None
    return {
        "baseline": baseline_value,
        "candidate": candidate_value,
        "delta": round(candidate_value - baseline_value, 3),
    }


def git_value(*argv: str) -> str:
    result = run_process(["git", *argv])
    if result.returncode != 0:
        return "unknown"
    return result.stdout.strip() or "unknown"


def gather_repo_state() -> dict[str, Any]:
    return {
        "commit": git_value("rev-parse", "HEAD"),
        "branch": git_value("branch", "--show-current"),
        "status_short": [line for line in git_value("status", "--short").splitlines() if line.strip()],
    }


def gather_docker_version() -> dict[str, Any]:
    result = run_process(["docker", "version", "--format", "{{json .}}"])
    if result.returncode != 0:
        return {
            "ok": False,
            "error": result.stderr.strip() or result.stdout.strip() or "docker version failed",
        }
    return {
        "ok": True,
        "details": json.loads(result.stdout),
    }
