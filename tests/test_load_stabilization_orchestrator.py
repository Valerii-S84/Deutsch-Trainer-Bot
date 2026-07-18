from __future__ import annotations

from scripts.load_stabilization_orchestrator import (
    BuildDefaults,
    build_runtime_spec,
    default_phase2_measurements,
    phase2_variants,
    phase4_variants,
    phase4_plan_command,
)
from scripts.load_stabilization_support import wait_for_http


def runtime_defaults() -> BuildDefaults:
    return BuildDefaults(
        default_env={},
        default_context={},
        default_postgres_settings={},
        default_redis_args=[],
        default_pgbouncer={
            "pool_mode": "transaction",
            "default_pool_size": "20",
        },
        default_prepare=[],
        default_measurements=[],
        top_level_images={
            "postgres_image": "postgres:16-alpine",
            "redis_image": "redis:7-alpine",
            "pgbouncer_image": "edoburu/pgbouncer:latest",
        },
        top_level_runtime={
            "postgres_user": "postgres",
            "postgres_password": "postgres",
            "postgres_shm_size": "128m",
            "ready_timeout_seconds": 60.0,
        },
    )


def direct_runtime() -> object:
    return build_runtime_spec(
        {
            "name": "pgbouncer-candidate",
            "env": {"DB_CONNECTION_BACKEND": "pgbouncer_transaction"},
        },
        runtime_defaults(),
    )


def test_build_runtime_spec_disables_pgbouncer_for_direct_backend() -> None:
    spec = build_runtime_spec(
        {
            "name": "direct-baseline",
            "role": "baseline",
            "env": {"DB_CONNECTION_BACKEND": "direct"},
        },
        runtime_defaults(),
    )

    assert spec.pgbouncer is None


def test_build_runtime_spec_keeps_pgbouncer_for_transaction_backend() -> None:
    spec = build_runtime_spec(
        {
            "name": "pgbouncer-candidate",
            "env": {"DB_CONNECTION_BACKEND": "pgbouncer_transaction"},
        },
        runtime_defaults(),
    )

    assert spec.pgbouncer == {
        "pool_mode": "transaction",
        "default_pool_size": "20",
    }


def test_phase2_variants_default_to_direct_and_pgbouncer() -> None:
    variants = phase2_variants({})

    assert [variant.name for variant in variants] == ["direct", "pgbouncer"]
    assert variants[0].pgbouncer is None
    assert variants[1].pgbouncer is not None
    assert variants[1].env["DB_CONNECTION_BACKEND"] == "pgbouncer_transaction"
    assert [command.name for command in variants[0].prepare] == ["migrate", "seed_worker_pipeline"]


def test_phase4_plan_command_uses_app_database_placeholders() -> None:
    command_spec, needs_seed = phase4_plan_command(
        {
            "mode": "steady",
            "target_rps": 100,
            "total_requests": 500,
            "workers_on": True,
        },
        runtime=direct_runtime(),
        session_offset=250,
    )

    assert needs_seed is True
    assert command_spec.env == {
        "DATABASE_URL": "{database_url_app}",
        "TEST_DATABASE_URL": "{database_url_direct}",
        "DB_CONNECTION_BACKEND": "{app_backend}",
    }
    assert command_spec.context["session_offset"] == "250"
    assert command_spec.command[-5:-1] == [
        "--session-offset",
        "{session_offset}",
        "--seeded-session-count",
        "{seed_session_count}",
    ]
    assert command_spec.command[-1] == "--workers-on"


def test_default_phase2_measurements_use_distinct_session_offsets() -> None:
    measurements = default_phase2_measurements({"total_requests": 100, "rps_points": ["10", "25", "50"]})

    assert [measurement.context["session_offset"] for measurement in measurements] == ["0", "100", "200"]
    assert measurements[1].command[-2:] == ["--session-offset", "{session_offset}"]


def test_build_runtime_spec_parses_multi_instance_stack_defaults() -> None:
    spec = build_runtime_spec(
        {
            "name": "webhook-multi",
            "stack": {
                "app_replicas": 3,
                "worker_replicas": 2,
                "image": "dtb-loadtest:local",
                "ingress": {
                    "runner": "docker",
                    "image": "caddy:2-alpine",
                    "command": ["run", "--config", "/etc/caddy/Caddyfile"],
                    "listen_port": 8090,
                    "ready_path": "/health",
                },
            },
        },
        runtime_defaults(),
    )

    assert spec.stack is not None
    assert spec.stack.app.replicas == 3
    assert spec.stack.worker.replicas == 2
    assert spec.stack.app.image == "dtb-loadtest:local"
    assert spec.stack.worker.image == "dtb-loadtest:local"
    assert spec.stack.ingress is not None
    assert spec.stack.app.command == ["python", "-m", "app.main", "serve-webhook"]
    assert spec.stack.app.env["BOT_FAKE_API_ENABLED"] == "True"
    assert spec.stack.app.env["TELEGRAM_WEBHOOK_HANDLE_IN_BACKGROUND"] == "False"
    assert spec.stack.app.env["TELEGRAM_WEBHOOK_REQUIRE_HTTPS"] == "False"
    assert spec.stack.app.env["DB_APP_REPLICA_COUNT"] == "3"
    assert spec.stack.app.env["DB_WORKER_REPLICA_COUNT"] == "2"
    assert spec.stack.worker.env["DB_APP_REPLICA_COUNT"] == "3"
    assert spec.stack.worker.env["DB_WORKER_REPLICA_COUNT"] == "2"
    assert spec.stack.app.env["TELEGRAM_WEBHOOK_PATH"] == "/telegram/webhook"
    assert spec.stack.ingress.runner == "docker"
    assert spec.stack.ingress.command == ["run", "--config", "/etc/caddy/Caddyfile"]
    assert spec.stack.ingress.listen_port == 8090


def test_phase4_plan_command_builds_webhook_burst_command() -> None:
    runtime = build_runtime_spec(
        {
            "name": "webhook-multi",
            "stack": {
                "app_replicas": 4,
                "worker_replicas": 2,
            },
        },
        runtime_defaults(),
    )

    command_spec, needs_seed = phase4_plan_command(
        {
            "mode": "burst",
            "total_requests": 500,
            "burst_window_seconds": 1,
            "burst_interval_seconds": 5,
        },
        runtime=runtime,
    )

    assert needs_seed is True
    assert command_spec.command[:3] == ["{python}", "scripts/load_stabilization_orchestrator.py", "webhook-load"]
    assert "--session-offset" in command_spec.command
    assert "--seeded-session-count" in command_spec.command
    assert "--base-url" in command_spec.command
    assert "--arrival-mode" in command_spec.command
    assert "--burst-window-seconds" in command_spec.command
    assert command_spec.context["session_offset"] == "0"
    assert command_spec.context["arrival_mode"] == "burst"
    assert command_spec.context["concurrency"] == "500"
    assert command_spec.context["target_rps"] == "100"


def test_phase4_plan_command_enables_pgbouncer_sampling() -> None:
    runtime = build_runtime_spec(
        {
            "name": "webhook-multi",
            "stack": {
                "app_replicas": 1,
                "worker_replicas": 1,
                "ingress": False,
            },
        },
        runtime_defaults(),
    )

    command_spec, needs_seed = phase4_plan_command(
        {
            "mode": "steady",
            "target_rps": 100,
            "total_requests": 500,
            "pgbouncer_sample_output": "qa_evidence/pgbouncer_pool_stats_20260703.json",
        },
        runtime=runtime,
    )

    assert needs_seed is True
    assert "--pgbouncer-sample-output" in command_spec.command
    assert command_spec.context["pgbouncer_sample_output"] == "qa_evidence/pgbouncer_pool_stats_20260703.json"
    assert command_spec.env["PGBOUNCER_ADMIN_DOCKER_CONTAINER"] == "{postgres_container}"
    assert command_spec.env["PGBOUNCER_TARGET_DATABASE"] == "{postgres_db}"


def test_summarize_pgbouncer_samples_filters_target_database() -> None:
    from scripts.load_stabilization_orchestrator import _summarize_pgbouncer_samples

    summary = _summarize_pgbouncer_samples(
        [
            {
                "pools": [
                    {
                        "database": "bot_db",
                        "cl_active": "10",
                        "cl_waiting": "3",
                        "sv_active": "20",
                        "sv_idle": "1",
                        "sv_used": "2",
                        "maxwait": "0.75",
                        "maxwait_us": "750000",
                    },
                    {
                        "database": "other",
                        "cl_active": "99",
                        "cl_waiting": "99",
                        "sv_active": "99",
                    },
                ]
            }
        ],
        config_rows=[
            {"key": "default_pool_size", "value": "20"},
            {"key": "reserve_pool_size", "value": "5"},
        ],
        target_database="bot_db",
        errors=[],
    )

    assert summary["pool_rows"] == 1
    assert summary["max_cl_waiting"] == 3.0
    assert summary["maxwait"] == 0.75
    assert summary["config"]["default_pool_size"] == "20"


def test_phase4_variants_assign_distinct_session_offsets_and_seed_capacity() -> None:
    variants = phase4_variants(
        {
            "variants": [{"name": "pgbouncer", "env": {"DB_CONNECTION_BACKEND": "pgbouncer_transaction"}}],
            "plans": [
                {"mode": "steady", "target_rps": 50, "total_requests": 9000},
                {"mode": "steady", "target_rps": 100, "total_requests": 18000},
            ],
        }
    )

    variant = variants[0]

    assert [measurement.context["session_offset"] for measurement in variant.measurements] == ["0", "9000"]
    assert variant.context["seed_session_count"] == "27000"
    assert [command.name for command in variant.prepare] == ["migrate", "seed_worker_pipeline"]


def test_phase4_variants_seed_webhook_stack_and_assign_offsets() -> None:
    variants = phase4_variants(
        {
            "stack": {
                "app_replicas": 3,
                "worker_replicas": 2,
                "ingress": {
                    "runner": "docker",
                    "image": "caddy:2-alpine",
                    "listen_port": 8090,
                },
            },
            "variants": [{"name": "webhook-stack"}],
            "plans": [
                {"mode": "steady", "target_rps": 100, "total_requests": 1000},
                {"mode": "burst", "total_requests": 500, "burst_window_seconds": 1, "burst_interval_seconds": 5},
            ],
        }
    )

    variant = variants[0]

    assert variant.stack is not None
    assert [command.name for command in variant.prepare] == ["migrate", "seed_worker_pipeline"]
    assert [measurement.name for measurement in variant.measurements] == ["steady_1000_requests", "burst_500_requests"]
    assert [measurement.context["session_offset"] for measurement in variant.measurements] == ["0", "1000"]
    assert variant.stack.ingress is not None
    assert variant.stack.ingress.command[:3] == ["{python}", "scripts/loadtest_ingress.py", "serve"]


def test_wait_for_http_retries_connection_reset(monkeypatch) -> None:
    calls = {"count": 0}

    class FakeResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    def fake_urlopen(url: str, timeout: int):
        del url, timeout
        calls["count"] += 1
        if calls["count"] == 1:
            raise ConnectionResetError(104, "connection reset by peer")
        return FakeResponse()

    monkeypatch.setattr("scripts.load_stabilization_support.urllib_request.urlopen", fake_urlopen)

    wait_for_http("http://example.test/ready", timeout_seconds=1.5)

    assert calls["count"] == 2
