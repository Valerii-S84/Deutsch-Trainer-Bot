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

from scripts.load_stabilization_support import (
    BUILT_LOADTEST_IMAGES,
    ServiceInstance,
    pick_free_port,
    wait_for_http,
    wait_for_port,
)


class _DockerServiceMixin:
    def _start_service_instance(self, role: str, spec: ServiceSpec, replica_index: int) -> ServiceInstance:
        if spec.runner == "docker":
            return self._start_docker_service_instance(role, spec, replica_index)
        return self._start_process_service_instance(role, spec, replica_index)

    def _start_docker_service_instance(self, role: str, spec: ServiceSpec, replica_index: int) -> ServiceInstance:
        image = self._resolve_service_image(role, spec)
        container_name = f"dtb-load-{role}-{self.safe_name}-{uuid4().hex[:8]}"
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
            caddyfile_path = self._render_ingress_caddyfile(
                spec,
                inside_docker=True,
                listen_port=spec.listen_port,
                replica_index=replica_index,
            )
            argv.extend(["-v", f"{caddyfile_path}:/etc/caddy/Caddyfile:ro"])
        for key, value in sorted(env.items()):
            argv.extend(["-e", f"{key}={value}"])
        argv.extend(spec.extra_args)
        argv.append(image)
        command = spec.command if spec.command else ["caddy", "run", "--config", "/etc/caddy/Caddyfile"]
        argv.extend([format_template(item, context) for item in command])
        try:
            self._docker(argv, check=True)
        except Exception:
            self._docker(["rm", "-f", container_name], check=False)
            raise
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
        if role == "ingress" and host_port is not None:
            caddyfile_path = self._render_ingress_caddyfile(
                spec,
                inside_docker=False,
                listen_port=host_port,
                replica_index=replica_index,
            )
            context["ingress_caddyfile"] = str(caddyfile_path)
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
            start_new_session=True,
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
        try:
            self._wait_for_service_instance(instance)
        except Exception as exc:
            _terminate_process_tree(process)
            log_excerpt = self._service_log_record(instance).get("excerpt", [])
            raise RuntimeError(
                f"{role} process failed readiness: {exc}; log_excerpt={log_excerpt}"
            ) from exc
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

    def _render_ingress_caddyfile(
        self,
        spec: ServiceSpec,
        *,
        inside_docker: bool,
        listen_port: int | None,
        replica_index: int,
    ) -> Path:
        if self.spec.stack is None:
            raise RuntimeError("ingress rendering requires a webhook stack")
        if listen_port is None:
            raise RuntimeError("ingress rendering requires a listen port")
        if inside_docker:
            app_targets = [instance.dial_address for instance in self.app_instances if instance.dial_address]
        else:
            app_targets = [
                f"127.0.0.1:{instance.host_port}"
                for instance in self.app_instances
                if instance.host_port is not None
            ]
        if not app_targets:
            raise RuntimeError("ingress rendering requires at least one app replica target")
        if spec.replicas > 1:
            shard_index = replica_index - 1
            sharded_targets = [
                target
                for index, target in enumerate(app_targets)
                if index % spec.replicas == shard_index
            ]
            if sharded_targets:
                app_targets = sharded_targets
        app_ready_path = self.spec.stack.app.ready_path or "/ready"
        ingress_health_path = spec.ready_path or "/health"
        caddyfile_path = self.runtime_dir / f"Caddyfile.ingress-{replica_index}"
        rendered = render_caddyfile(
            parse_targets(app_targets),
            config=IngressConfig(
                listen_address=f":{listen_port}",
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
                    "COPY scripts /app/scripts",
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
            if instance.process is None:
                wait_for_port(instance.host_port, timeout_seconds=self.spec.ready_timeout_seconds)
            else:
                self._wait_for_process_port(instance)
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

    def _wait_for_process_port(self, instance: ServiceInstance) -> None:
        assert instance.host_port is not None
        assert instance.process is not None
        deadline = time.time() + self.spec.ready_timeout_seconds
        while time.time() < deadline:
            if instance.process.poll() is not None:
                raise RuntimeError(f"{instance.role} process exited before opening port")
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.settimeout(1.0)
                if sock.connect_ex(("127.0.0.1", instance.host_port)) == 0:
                    return
            time.sleep(1.0)
        raise TimeoutError(f"Timed out waiting for 127.0.0.1:{instance.host_port}")

    def _stop_service_instances(self, instances: Sequence[ServiceInstance]) -> None:
        for instance in reversed(instances):
            self._stop_service_instance(instance)

    def _stop_service_instance(self, instance: ServiceInstance) -> None:
        try:
            if instance.runner == "docker":
                self._docker(["rm", "-f", instance.identifier], check=False)
            elif instance.process is not None:
                _terminate_process_tree(instance.process)
        except Exception as exc:  # noqa: BLE001
            self.cleanup_errors.append(f"{instance.role}:{instance.identifier}:{exc.__class__.__name__}: {exc}")

    def _stop_ingress(self) -> None:
        if not self.ingress_instances:
            return
        self._stop_service_instances(self.ingress_instances)

    def _docker(self, args: Sequence[str], *, check: bool) -> ProcessResult:
        result = run_process(["docker", *args])
        if check and result.returncode != 0:
            message = result.stderr.strip() or result.stdout.strip() or f"docker {' '.join(args)} failed"
            raise RuntimeError(message)
        return result


class _DockerInfrastructureMixin:
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
