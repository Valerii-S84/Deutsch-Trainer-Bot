from __future__ import annotations

import os
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
        try:
            with urllib_request.urlopen(url, timeout=3) as response:  # nosec B310
                if 200 <= response.status < 500:
                    return
        except (urllib_error.URLError, OSError, TimeoutError):
            pass
        time.sleep(1.0)
    raise TimeoutError(f"Timed out waiting for HTTP endpoint {url}")


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


class DockerRuntime:
    def __init__(self, spec: RuntimeSpec, *, keep_running: bool = False) -> None:
        self.spec = spec
        self.keep_running = keep_running
        suffix = f"{sanitize_name(spec.name)}-{uuid4().hex[:8]}"
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
        self.ingress_instance: ServiceInstance | None = None
        self.started = False
        self.stack_started = False
        self.cleaned_up = False

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
        context["app_replica_count"] = str(len(self.app_instances))
        context["worker_replica_count"] = str(len(self.worker_instances))
        context["app_replica_urls_csv"] = ",".join(app_urls)
        context["app_replica_urls_json"] = "[" + ",".join(f'"{url}"' for url in app_urls) + "]"
        app_targets = [instance.dial_address for instance in self.app_instances if instance.dial_address]
        context["app_replica_targets_csv"] = ",".join(app_targets)
        context["app_replica_targets_json"] = "[" + ",".join(f'"{target}"' for target in app_targets) + "]"
        for index, url in enumerate(app_urls, start=1):
            context[f"app_replica_{index}_url"] = url
        for index, target in enumerate(app_targets, start=1):
            context[f"app_replica_{index}_target"] = target
        if self.ingress_instance and self.ingress_instance.url:
            context["ingress_base_url"] = self.ingress_instance.url
            context["ingress_port"] = str(self.ingress_instance.host_port or "")
        elif app_urls:
            context["ingress_base_url"] = app_urls[0]
            context["ingress_port"] = str(self.app_instances[0].host_port or "")
        else:
            context["ingress_base_url"] = ""
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
            "ingress": None if self.ingress_instance is None else self._service_log_record(self.ingress_instance),
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
        self._stop_service_instances(self.app_instances)
        self._stop_ingress()
        self._docker(["rm", "-f", self.postgres_container], check=False)
        self._docker(["rm", "-f", self.redis_container], check=False)
        if self.pgbouncer_container is not None:
            self._docker(["rm", "-f", self.pgbouncer_container], check=False)
        self._docker(["network", "rm", self.network_name], check=False)
        self._docker(["volume", "rm", self.pg_volume_name], check=False)
        shutil.rmtree(self.runtime_dir, ignore_errors=True)
        self.cleaned_up = True

    def _stack_description(self) -> dict[str, Any] | None:
        if self.spec.stack is None:
            return None
        return {
            "mode": self.spec.stack.mode,
            "webhook_path": self.spec.stack.webhook_path,
            "app": [self._instance_description(instance) for instance in self.app_instances],
            "worker": [self._instance_description(instance) for instance in self.worker_instances],
            "ingress": None if self.ingress_instance is None else self._instance_description(self.ingress_instance),
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
        self.ingress_instance = self._start_service_instance("ingress", spec, 1)

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

    def _start_service_instance(self, role: str, spec: ServiceSpec, replica_index: int) -> ServiceInstance:
        if spec.runner == "docker":
            return self._start_docker_service_instance(role, spec, replica_index)
        return self._start_process_service_instance(role, spec, replica_index)

    def _start_docker_service_instance(self, role: str, spec: ServiceSpec, replica_index: int) -> ServiceInstance:
        image = self._resolve_service_image(role, spec)
        container_name = f"dtb-load-{role}-{sanitize_name(self.spec.name)}-{uuid4().hex[:8]}"
        host_port = pick_free_port() if spec.listen_port is not None else None
        context = self._service_context(role, spec, replica_index, host_port)
        env = self._format_service_env(self._docker_base_service_env(), spec.env, context)
        argv = [
            "run",
            "-d",
            "--name",
            container_name,
            "--network",
            self.network_name,
        ]
        if host_port is not None and spec.listen_port is not None:
            argv.extend(["-p", f"{host_port}:{spec.listen_port}"])
        if role == "ingress":
            caddyfile_path = self._render_ingress_caddyfile(spec)
            argv.extend(["-v", f"{caddyfile_path}:/etc/caddy/Caddyfile:ro"])
        for key, value in sorted(env.items()):
            argv.extend(["-e", f"{key}={value}"])
        argv.extend(spec.extra_args)
        argv.append(image)
        command = spec.command if spec.command else ["run", "--config", "/etc/caddy/Caddyfile"]
        argv.extend([format_template(item, context) for item in command])
        self._docker(argv, check=True)
        instance = ServiceInstance(
            role=role,
            replica_index=replica_index,
            runner="docker",
            identifier=container_name,
            dial_address=None if spec.listen_port is None else f"{container_name}:{spec.listen_port}",
            host_port=host_port,
            internal_port=spec.listen_port,
            ready_path=spec.ready_path,
            url=self._service_url(host_port),
        )
        self._wait_for_service_instance(instance)
        return instance

    def _start_process_service_instance(self, role: str, spec: ServiceSpec, replica_index: int) -> ServiceInstance:
        host_port = pick_free_port() if spec.listen_port is not None else None
        context = self._service_context(role, spec, replica_index, host_port)
        env = self._format_service_env(self.base_env(), spec.env, context)
        argv = [format_template(item, context) for item in spec.command]
        log_path = self.runtime_dir / f"{role}-{replica_index}.log"
        handle = log_path.open("w", encoding="utf-8")
        process = subprocess.Popen(  # noqa: S603
            argv,
            cwd=str((ROOT if spec.workdir is None else (ROOT / spec.workdir)).resolve()),
            env=env,
            stdout=handle,
            stderr=subprocess.STDOUT,
            text=True,
        )
        handle.close()
        instance = ServiceInstance(
            role=role,
            replica_index=replica_index,
            runner="process",
            identifier=f"{role}-{process.pid}",
            dial_address=None if host_port is None else f"127.0.0.1:{host_port}",
            host_port=host_port,
            internal_port=spec.listen_port,
            ready_path=spec.ready_path,
            url=self._service_url(host_port),
            log_path=str(log_path),
            process=process,
        )
        self._wait_for_service_instance(instance)
        return instance

    def _service_context(
        self,
        role: str,
        spec: ServiceSpec,
        replica_index: int,
        host_port: int | None,
    ) -> dict[str, str]:
        context = self.context()
        listen_port = spec.listen_port or host_port or ""
        if spec.runner == "process" and host_port is not None:
            listen_port = host_port
        context.update(
            {
                "service_role": role,
                "replica_index": str(replica_index),
                "listen_port": str(listen_port),
                "host_port": str(host_port or ""),
            }
        )
        if self.spec.stack is not None:
            context["app_ready_path"] = self.spec.stack.app.ready_path or "/ready"
        if role == "ingress" and host_port is not None:
            context["ingress_port"] = str(host_port)
        return context

    def _format_service_env(
        self,
        base_env: dict[str, str],
        raw_env: dict[str, str],
        context: dict[str, str],
    ) -> dict[str, str]:
        env = dict(base_env)
        env.update({key: format_template(value, context) for key, value in raw_env.items()})
        return env

    def _resolve_service_image(self, role: str, spec: ServiceSpec) -> str:
        if spec.build is None:
            assert spec.image is not None
            return spec.image
        image = spec.image or f"dtb-load-{role}:{sanitize_name(self.spec.name)}"
        self._ensure_image_built(image, spec.build)
        return image

    def _ensure_image_built(self, image: str, build: DockerBuildSpec) -> None:
        if image in BUILT_LOADTEST_IMAGES:
            return
        dockerfile_path = self._materialize_dockerfile(build)
        build_context = str((ROOT / build.context).resolve())
        self._docker(["build", "-t", image, "-f", str(dockerfile_path), build_context], check=True)
        BUILT_LOADTEST_IMAGES.add(image)

    def _render_ingress_caddyfile(self, spec: ServiceSpec) -> Path:
        if self.spec.stack is None:
            raise RuntimeError("ingress rendering requires a webhook stack")
        app_targets = [instance.dial_address for instance in self.app_instances if instance.dial_address]
        if not app_targets:
            raise RuntimeError("ingress rendering requires at least one app replica target")
        app_ready_path = self.spec.stack.app.ready_path or "/ready"
        ingress_health_path = spec.ready_path or "/health"
        caddyfile_path = self.runtime_dir / "Caddyfile.ingress"
        rendered = render_caddyfile(
            parse_targets(app_targets),
            config=IngressConfig(
                listen_address=f"0.0.0.0:{spec.listen_port}",
                ingress_health_path=ingress_health_path,
                ready_path=app_ready_path,
                webhook_path=self.spec.stack.webhook_path,
            ),
        )
        caddyfile_path.write_text(rendered, encoding="utf-8")
        return caddyfile_path

    def _materialize_dockerfile(self, build: DockerBuildSpec):
        if build.dockerfile is not None:
            return (ROOT / build.dockerfile).resolve()
        dockerfile_path = self.runtime_dir / "Dockerfile.loadtest"
        dockerfile_path.write_text(
            "\n".join(
                [
                    "FROM python:3.12-slim",
                    "ENV PYTHONDONTWRITEBYTECODE=1",
                    "ENV PYTHONUNBUFFERED=1",
                    "WORKDIR /app",
                    "COPY pyproject.toml /app/pyproject.toml",
                    "COPY app /app/app",
                    "COPY tests /app/tests",
                    "RUN pip install --no-cache-dir --upgrade pip && pip install --no-cache-dir .",
                    'CMD ["python", "-m", "app.main"]',
                    "",
                ]
            ),
            encoding="utf-8",
        )
        return dockerfile_path

    def _service_url(self, host_port: int | None) -> str | None:
        if host_port is None:
            return None
        return f"http://127.0.0.1:{host_port}"

    def _wait_for_service_instance(self, instance: ServiceInstance) -> None:
        if instance.host_port is not None:
            wait_for_port(instance.host_port, timeout_seconds=self.spec.ready_timeout_seconds)
            if instance.url and instance.ready_path:
                wait_for_http(
                    f"{instance.url}{instance.ready_path}",
                    timeout_seconds=self.spec.ready_timeout_seconds,
                )
            return
        if instance.process is not None:
            time.sleep(0.5)
            if instance.process.poll() is not None:
                raise RuntimeError(f"{instance.role} process exited before measurements started")

    def _stop_service_instances(self, instances: Sequence[ServiceInstance]) -> None:
        for instance in reversed(instances):
            if instance.runner == "docker":
                self._docker(["rm", "-f", instance.identifier], check=False)
            elif instance.process is not None:
                instance.process.terminate()
                try:
                    instance.process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    instance.process.kill()
                    instance.process.wait(timeout=5)

    def _stop_ingress(self) -> None:
        if self.ingress_instance is None:
            return
        self._stop_service_instances([self.ingress_instance])

    def _docker(self, args: Sequence[str], *, check: bool) -> ProcessResult:
        result = run_process(["docker", *args])
        if check and result.returncode != 0:
            message = result.stderr.strip() or result.stdout.strip() or f"docker {' '.join(args)} failed"
            raise RuntimeError(message)
        return result

    def _start_postgres(self) -> None:
        argv = [
            "run",
            "-d",
            "--name",
            self.postgres_container,
            "--network",
            self.network_name,
            "--shm-size",
            self.spec.postgres_shm_size,
            "--mount",
            f"type=volume,source={self.pg_volume_name},target=/var/lib/postgresql/data",
            "-p",
            f"{self.postgres_port}:5432",
            "-e",
            f"POSTGRES_USER={self.spec.postgres_user}",
            "-e",
            f"POSTGRES_PASSWORD={self.spec.postgres_password}",
            "-e",
            f"POSTGRES_DB={self.spec.postgres_db}",
            self.spec.postgres_image,
            "postgres",
        ]
        for key, value in sorted(self.spec.postgres_settings.items()):
            argv.extend(["-c", f"{key}={value}"])
        self._docker(argv, check=True)
        self._wait_for_postgres()

    def _start_redis(self) -> None:
        argv = [
            "run",
            "-d",
            "--name",
            self.redis_container,
            "--network",
            self.network_name,
            "-p",
            f"{self.redis_port}:6379",
            self.spec.redis_image,
            "redis-server",
            "--save",
            "60",
            "1",
            "--loglevel",
            "warning",
            *self.spec.redis_args,
        ]
        self._docker(argv, check=True)
        self._wait_for_redis()

    def _start_pgbouncer(self) -> None:
        if self.pgbouncer_port is None or self.pgbouncer_container is None:
            raise RuntimeError("PgBouncer runtime is not configured")
        self._write_pgbouncer_files()
        argv = [
            "run",
            "-d",
            "--name",
            self.pgbouncer_container,
            "--network",
            self.network_name,
            "--entrypoint",
            "pgbouncer",
            "-p",
            f"{self.pgbouncer_port}:6432",
            "-v",
            f"{self.runtime_dir / 'pgbouncer.ini'}:/etc/pgbouncer/pgbouncer.ini:ro",
            "-v",
            f"{self.runtime_dir / 'userlist.txt'}:/etc/pgbouncer/userlist.txt:ro",
        ]
        argv.append(self.spec.pgbouncer_image)
        argv.append("/etc/pgbouncer/pgbouncer.ini")
        self._docker(argv, check=True)
        wait_for_port(self.pgbouncer_port, timeout_seconds=self.spec.ready_timeout_seconds)

    def _write_pgbouncer_files(self) -> None:
        settings = {
            "pool_mode": "transaction",
            "max_client_conn": "200",
            "default_pool_size": "20",
            "reserve_pool_size": "5",
            "ignore_startup_parameters": "extra_float_digits",
            "server_reset_query": "DISCARD ALL",
            **(self.spec.pgbouncer or {}),
        }
        pgbouncer_lines = [
            "[databases]",
            (
                f"{self.spec.postgres_db} = host={self.postgres_container} port=5432 "
                f"dbname={self.spec.postgres_db} user={self.spec.postgres_user} "
                f"password={self.spec.postgres_password}"
            ),
            "",
            "[pgbouncer]",
            "listen_addr = 0.0.0.0",
            "listen_port = 6432",
            "auth_type = plain",
            "auth_file = /etc/pgbouncer/userlist.txt",
            f"admin_users = {self.spec.postgres_user}",
            f"stats_users = {self.spec.postgres_user}",
        ]
        for key, value in sorted(settings.items()):
            pgbouncer_lines.append(f"{key} = {value}")
        (self.runtime_dir / "pgbouncer.ini").write_text("\n".join(pgbouncer_lines) + "\n", encoding="utf-8")
        (self.runtime_dir / "userlist.txt").write_text(
            f"\"{self.spec.postgres_user}\" \"{self.spec.postgres_password}\"\n",
            encoding="utf-8",
        )

    def _wait_for_postgres(self) -> None:
        deadline = time.time() + self.spec.ready_timeout_seconds
        while time.time() < deadline:
            result = self._docker(
                [
                    "exec",
                    self.postgres_container,
                    "pg_isready",
                    "-U",
                    self.spec.postgres_user,
                    "-d",
                    self.spec.postgres_db,
                ],
                check=False,
            )
            if result.returncode == 0:
                return
            time.sleep(1.0)
        raise TimeoutError(f"Timed out waiting for postgres container {self.postgres_container}")

    def _wait_for_redis(self) -> None:
        deadline = time.time() + self.spec.ready_timeout_seconds
        while time.time() < deadline:
            result = self._docker(["exec", self.redis_container, "redis-cli", "ping"], check=False)
            if result.returncode == 0 and "PONG" in result.stdout:
                return
            time.sleep(1.0)
        raise TimeoutError(f"Timed out waiting for redis container {self.redis_container}")

    def _container_log_record(self, container_name: str) -> dict[str, Any]:
        result = self._docker(["logs", container_name], check=False)
        combined = "\n".join(part for part in (result.stdout.strip(), result.stderr.strip()) if part)
        checkpoint_lines = [
            line
            for line in combined.splitlines()
            if "checkpoint" in line.lower()
        ]
        return {
            "container": container_name,
            "returncode": result.returncode,
            "excerpt": excerpt(combined, max_lines=40),
            "checkpoint_lines": checkpoint_lines[:20],
        }

    def _service_log_record(self, instance: ServiceInstance) -> dict[str, Any]:
        if instance.runner == "docker":
            return self._container_log_record(instance.identifier)
        if instance.log_path is None:
            return {
                "container": instance.identifier,
                "returncode": None,
                "excerpt": [],
                "checkpoint_lines": [],
            }
        log_path = (
            ROOT / instance.log_path
            if not os.path.isabs(instance.log_path)
            else Path(instance.log_path)
        )
        try:
            content = log_path.read_text(encoding="utf-8")
        except OSError:
            content = ""
        checkpoint_lines = [line for line in content.splitlines() if "checkpoint" in line.lower()]
        return {
            "container": instance.identifier,
            "returncode": None if instance.process is None else instance.process.poll(),
            "excerpt": excerpt(content, max_lines=40),
            "checkpoint_lines": checkpoint_lines[:20],
        }


def redact_url(value: str) -> str:
    if "@" not in value:
        return value
    prefix, suffix = value.rsplit("@", 1)
    if ":" not in prefix:
        return value
    scheme, rest = prefix.split("://", 1)
    user = rest.split(":", 1)[0]
    return f"{scheme}://{user}:***@{suffix}"
