from __future__ import annotations

import os
import signal
import socket
import shutil
import subprocess
import sys
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib import error as urllib_error
from urllib import request as urllib_request
from uuid import uuid4

try:
    from loadtest_ingress import IngressConfig, parse_targets, render_caddyfile
    from load_stabilization_common import (
        DEFAULT_PGBOUNCER_IMAGE,
        DEFAULT_POSTGRES_IMAGE,
        DEFAULT_REDIS_IMAGE,
        ROOT,
        CommandSpec,
        DockerBuildSpec,
        ProcessResult,
        RuntimeSpec,
        ServiceSpec,
        WebhookStackSpec,
        build_comparisons,
        excerpt,
        format_template,
        gather_docker_version,
        gather_repo_state,
        normalize_command,
        normalize_str_list,
        normalize_str_map,
        now_utc,
        resolve_evidence_path,
        run_command_spec,
        run_process,
        sanitize_name,
        write_json,
    )
except ImportError:  # pragma: no cover - package import path for tests
    from scripts.loadtest_ingress import IngressConfig, parse_targets, render_caddyfile
    from scripts.load_stabilization_common import (
        DEFAULT_PGBOUNCER_IMAGE,
        DEFAULT_POSTGRES_IMAGE,
        DEFAULT_REDIS_IMAGE,
        ROOT,
        CommandSpec,
        DockerBuildSpec,
        ProcessResult,
        RuntimeSpec,
        ServiceSpec,
        WebhookStackSpec,
        build_comparisons,
        excerpt,
        format_template,
        gather_docker_version,
        gather_repo_state,
        normalize_command,
        normalize_str_list,
        normalize_str_map,
        now_utc,
        resolve_evidence_path,
        run_command_spec,
        run_process,
        sanitize_name,
        write_json,
    )


def pick_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def wait_for_port(port: int, *, timeout_seconds: float) -> None:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(1.0)
            if sock.connect_ex(("127.0.0.1", port)) == 0:
                return
        time.sleep(1.0)
    raise TimeoutError(f"Timed out waiting for 127.0.0.1:{port}")


def wait_for_http(url: str, *, timeout_seconds: float) -> None:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        if _http_endpoint_ready(url):
            return
        time.sleep(1.0)
    raise TimeoutError(f"Timed out waiting for HTTP endpoint {url}")


def _http_endpoint_ready(url: str) -> bool:
    try:
        with urllib_request.urlopen(url, timeout=3) as response:  # nosec B310
            return 200 <= response.status < 500
    except (urllib_error.URLError, OSError, TimeoutError):
        return False


BUILT_LOADTEST_IMAGES: set[str] = set()


@dataclass(slots=True)
class ServiceInstance:
    role: str
    replica_index: int
    runner: str
    identifier: str
    dial_address: str | None = None
    host_port: int | None = None
    internal_port: int | None = None
    ready_path: str | None = None
    url: str | None = None
    log_path: str | None = None
    process: subprocess.Popen[str] | None = None


class _DockerRuntimeBase:
    def __init__(self, spec: RuntimeSpec, *, keep_running: bool = False) -> None:
        self.spec = spec
        self.keep_running = keep_running
        self.safe_name = sanitize_name(spec.name)[:32]
        suffix = f"{self.safe_name}-{uuid4().hex[:8]}"
        self.network_name = f"dtb-load-net-{suffix}"
        self.pg_volume_name = f"dtb-load-pgdata-{suffix}"
        self.postgres_container = f"dtb-load-pg-{suffix}"
        self.redis_container = f"dtb-load-redis-{suffix}"
        self.pgbouncer_container = f"dtb-load-pgb-{suffix}" if spec.pgbouncer else None
        self.runtime_dir = ROOT / ".tmp" / f"load-stabilization-{suffix}"
        self.postgres_port = pick_free_port()
        self.redis_port = pick_free_port()
        self.pgbouncer_port = pick_free_port() if spec.pgbouncer else None
        self.app_instances: list[ServiceInstance] = []
        self.worker_instances: list[ServiceInstance] = []
        self.ingress_instances: list[ServiceInstance] = []
        self.started = False
        self.stack_started = False
        self.cleaned_up = False
        self.cleanup_errors: list[str] = []

    @property
    def app_backend(self) -> str:
        return "pgbouncer_transaction" if self.spec.pgbouncer else "direct"

    @property
    def direct_database_url(self) -> str:
        return (
            "postgresql+asyncpg://"
            f"{self.spec.postgres_user}:{self.spec.postgres_password}"
            f"@127.0.0.1:{self.postgres_port}/{self.spec.postgres_db}"
        )

    @property
    def direct_database_url_internal(self) -> str:
        return (
            "postgresql+asyncpg://"
            f"{self.spec.postgres_user}:{self.spec.postgres_password}"
            f"@{self.postgres_container}:5432/{self.spec.postgres_db}"
        )

    @property
    def app_database_url(self) -> str:
        if not self.spec.pgbouncer or self.pgbouncer_port is None:
            return self.direct_database_url
        return (
            "postgresql+asyncpg://"
            f"{self.spec.postgres_user}:{self.spec.postgres_password}"
            f"@127.0.0.1:{self.pgbouncer_port}/{self.spec.postgres_db}"
        )

    @property
    def app_database_url_internal(self) -> str:
        if not self.spec.pgbouncer or self.pgbouncer_container is None:
            return self.direct_database_url_internal
        return (
            "postgresql+asyncpg://"
            f"{self.spec.postgres_user}:{self.spec.postgres_password}"
            f"@{self.pgbouncer_container}:6432/{self.spec.postgres_db}"
        )

    @property
    def redis_url(self) -> str:
        return f"redis://127.0.0.1:{self.redis_port}/0"

    @property
    def redis_url_internal(self) -> str:
        return f"redis://{self.redis_container}:6379/0"

    def base_env(self) -> dict[str, str]:
        env = dict(os.environ)
        env.update(
            {
                "APP_ENV": "development",
                "DATABASE_URL": self.app_database_url,
                "TEST_DATABASE_URL": self.direct_database_url,
                "REDIS_URL": self.redis_url,
                "DB_CONNECTION_BACKEND": self.app_backend,
                "BOT_TOKEN": "123456:DTBLOADTESTTOKEN",
                "QUIZ_BANK_API_BASE_URL": "https://api.quiz-bank.example.internal",
                "QUIZ_BANK_EDGE_API_KEY": "",
                "QUIZ_BANK_CONSUMER_ID": "",
                "QUIZ_BANK_CONSUMER_API_KEY": "",
            }
        )
        if self.spec.pgbouncer is not None:
            env["DB_PGBOUNCER_MAX_CLIENT_CONN"] = str(self.spec.pgbouncer.get("max_client_conn", "200"))
        env.update(self.spec.env)
        return env

    def context(self) -> dict[str, str]:
        context = {
            "python": sys.executable,
            "root": str(ROOT),
            "variant_name": self.spec.name,
            "variant_role": self.spec.role,
            "postgres_container": self.postgres_container,
            "postgres_user": self.spec.postgres_user,
            "postgres_password": self.spec.postgres_password,
            "postgres_db": self.spec.postgres_db,
            "database_url": self.app_database_url,
            "database_url_app": self.app_database_url,
            "database_url_app_internal": self.app_database_url_internal,
            "database_url_direct": self.direct_database_url,
            "database_url_direct_internal": self.direct_database_url_internal,
            "test_database_url": self.direct_database_url,
            "redis_url": self.redis_url,
            "redis_url_internal": self.redis_url_internal,
            "app_backend": self.app_backend,
            "postgres_port": str(self.postgres_port),
            "redis_port": str(self.redis_port),
            "pgbouncer_port": str(self.pgbouncer_port or ""),
            "pgbouncer_container": self.pgbouncer_container or "",
            "webhook_path": self.spec.stack.webhook_path if self.spec.stack else "",
            "webhook_secret": self.spec.stack.webhook_secret if self.spec.stack else "",
            **self.spec.context,
        }
        app_urls = [instance.url for instance in self.app_instances if instance.url]
        context.update(app_replica_count=str(len(self.app_instances)), worker_replica_count=str(len(self.worker_instances)))
        context["app_replica_urls_csv"] = ",".join(app_urls)
        context["app_replica_urls_json"] = "[" + ",".join(f'"{url}"' for url in app_urls) + "]"
        app_targets = [instance.dial_address for instance in self.app_instances if instance.dial_address]
        context["app_replica_targets_csv"] = ",".join(app_targets)
        context["app_replica_targets_json"] = "[" + ",".join(f'"{target}"' for target in app_targets) + "]"
        for index, url in enumerate(app_urls, start=1):
            context[f"app_replica_{index}_url"] = url
        for index, target in enumerate(app_targets, start=1):
            context[f"app_replica_{index}_target"] = target
        ingress_urls = [instance.url for instance in self.ingress_instances if instance.url]
        context["ingress_replica_count"] = str(len(self.ingress_instances))
        context["ingress_base_urls_csv"] = ",".join(ingress_urls)
        context["ingress_base_urls_json"] = "[" + ",".join(f'"{url}"' for url in ingress_urls) + "]"
        for index, url in enumerate(ingress_urls, start=1):
            context[f"ingress_replica_{index}_url"] = url
        if ingress_urls:
            context["ingress_base_url"] = ingress_urls[0]
            context["ingress_port"] = str(self.ingress_instances[0].host_port or "")
        elif app_urls:
            context["ingress_base_url"] = app_urls[0]
            context["ingress_base_urls_csv"] = ",".join(app_urls)
            context["ingress_base_urls_json"] = "[" + ",".join(f'"{url}"' for url in app_urls) + "]"
            context["ingress_port"] = str(self.app_instances[0].host_port or "")
        else:
            context["ingress_base_url"] = ""
            context["ingress_base_urls_csv"] = ""
            context["ingress_base_urls_json"] = "[]"
            context["ingress_port"] = ""
        return context

    def describe(self) -> dict[str, Any]:
        return {
            "postgres": {
                "container": self.postgres_container,
                "image": self.spec.postgres_image,
                "host_port": self.postgres_port,
                "database": self.spec.postgres_db,
                "settings": self.spec.postgres_settings,
            },
            "redis": {
                "container": self.redis_container,
                "image": self.spec.redis_image,
                "host_port": self.redis_port,
            },
            "pgbouncer": None
            if not self.spec.pgbouncer
            else {
                "container": self.pgbouncer_container,
                "image": self.spec.pgbouncer_image,
                "host_port": self.pgbouncer_port,
                "settings": self.spec.pgbouncer,
            },
            "network": self.network_name,
            "keep_running": self.keep_running,
            "stack_started": self.stack_started,
            "stack": self._stack_description(),
            "cleanup_completed": self.cleaned_up,
            "cleanup_errors": list(self.cleanup_errors),
            "database_url_redacted": redact_url(self.app_database_url),
            "direct_database_url_redacted": redact_url(self.direct_database_url),
            "redis_url_redacted": self.redis_url,
        }

    def collect_logs(self) -> dict[str, Any]:
        logs = {
            "postgres": self._container_log_record(self.postgres_container),
            "redis": self._container_log_record(self.redis_container),
            "app": [self._service_log_record(instance) for instance in self.app_instances],
            "worker": [self._service_log_record(instance) for instance in self.worker_instances],
            "ingress": [self._service_log_record(instance) for instance in self.ingress_instances],
        }
        if self.pgbouncer_container is not None:
            logs["pgbouncer"] = self._container_log_record(self.pgbouncer_container)
        else:
            logs["pgbouncer"] = None
        return logs

    def start(self) -> None:
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        self._docker(["network", "create", self.network_name], check=True)
        self._docker(["volume", "create", self.pg_volume_name], check=True)
        self._start_postgres()
        self._start_redis()
        if self.spec.pgbouncer:
            self._start_pgbouncer()
        self.started = True

    def start_stack(self) -> None:
        if self.stack_started or self.spec.stack is None:
            return
        self._start_worker_replicas(self.spec.stack.worker)
        self._start_app_replicas(self.spec.stack.app)
        self._start_ingress(self.spec.stack.ingress)
        self.stack_started = True

    def stop(self) -> None:
        if self.keep_running:
            return
        self._stop_service_instances(self.worker_instances)
        self._stop_ingress()
        self._stop_service_instances(self.app_instances)
        self._docker(["rm", "-f", self.postgres_container], check=False)
        self._docker(["rm", "-f", self.redis_container], check=False)
        if self.pgbouncer_container is not None:
            self._docker(["rm", "-f", self.pgbouncer_container], check=False)
        self._docker(["network", "rm", self.network_name], check=False)
        self._docker(["volume", "rm", self.pg_volume_name], check=False)
        shutil.rmtree(self.runtime_dir, ignore_errors=True)
        self.cleaned_up = True

from scripts.load_stabilization_docker import _DockerInfrastructureMixin, _DockerServiceMixin


class DockerRuntime(_DockerServiceMixin, _DockerInfrastructureMixin, _DockerRuntimeBase):
    def _stack_description(self) -> dict[str, Any] | None:
        if self.spec.stack is None:
            return None
        return {
            "mode": self.spec.stack.mode,
            "webhook_path": self.spec.stack.webhook_path,
            "app": [self._instance_description(instance) for instance in self.app_instances],
            "worker": [self._instance_description(instance) for instance in self.worker_instances],
            "ingress": [self._instance_description(instance) for instance in self.ingress_instances],
        }

    def _instance_description(self, instance: ServiceInstance) -> dict[str, Any]:
        return {
            "role": instance.role,
            "runner": instance.runner,
            "identifier": instance.identifier,
            "replica_index": instance.replica_index,
            "dial_address": instance.dial_address,
            "host_port": instance.host_port,
            "internal_port": instance.internal_port,
            "url": instance.url,
            "ready_path": instance.ready_path,
            "log_path": instance.log_path,
        }

    def _docker_base_service_env(self) -> dict[str, str]:
        env = self.base_env()
        env.update(
            {
                "DATABASE_URL": self.app_database_url_internal,
                "TEST_DATABASE_URL": self.direct_database_url_internal,
                "REDIS_URL": self.redis_url_internal,
            }
        )
        return env

    def _start_app_replicas(self, spec: ServiceSpec) -> None:
        self._ensure_service_spec("app", spec)
        for replica_index in range(1, spec.replicas + 1):
            self.app_instances.append(self._start_service_instance("app", spec, replica_index))

    def _start_worker_replicas(self, spec: ServiceSpec) -> None:
        self._ensure_service_spec("worker", spec)
        for replica_index in range(1, spec.replicas + 1):
            self.worker_instances.append(self._start_service_instance("worker", spec, replica_index))

    def _start_ingress(self, spec: ServiceSpec | None) -> None:
        if spec is None:
            if len(self.app_instances) > 1:
                raise RuntimeError("multi-instance webhook runtime requires an ingress service definition")
            return
        self._ensure_service_spec("ingress", spec)
        for replica_index in range(1, spec.replicas + 1):
            self.ingress_instances.append(self._start_service_instance("ingress", spec, replica_index))

    def _ensure_service_spec(self, role: str, spec: ServiceSpec) -> None:
        if spec.runner not in {"docker", "process"}:
            raise RuntimeError(f"{role} runner must be docker or process")
        if spec.replicas < 1:
            raise RuntimeError(f"{role} replicas must be >= 1")
        if spec.runner == "process" and not spec.command:
            raise RuntimeError(f"{role} process service requires an explicit command")
        if spec.runner == "docker" and not spec.image and not spec.build:
            raise RuntimeError(f"{role} docker service requires image or build")
        if role in {"app", "ingress"} and spec.listen_port is None:
            raise RuntimeError(f"{role} service requires listen_port for load-harness routing")



def redact_url(value: str) -> str:
    if "@" not in value:
        return value
    prefix, suffix = value.rsplit("@", 1)
    if ":" not in prefix:
        return value
    scheme, rest = prefix.split("://", 1)
    user = rest.split(":", 1)[0]
    return f"{scheme}://{user}:***@{suffix}"


def _terminate_process_tree(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    _signal_process_tree(process, signal.SIGTERM)
    try:
        process.wait(timeout=10)
        return
    except subprocess.TimeoutExpired:
        _signal_process_tree(process, signal.SIGKILL)
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"process {process.pid} did not exit after SIGKILL") from exc


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
