from __future__ import annotations

import asyncio
import pytest
from aiohttp import web

from scripts.loadtest_ingress import IngressConfig
from scripts.loadtest_ingress import main
from scripts.loadtest_ingress import parse_upstream_urls
from scripts.loadtest_ingress import parse_targets
from scripts.loadtest_ingress import render_caddyfile
from scripts.loadtest_ingress import RoundRobinUpstreams


def test_render_caddyfile_includes_all_replica_targets_and_health_checks() -> None:
    rendered = render_caddyfile(
        parse_targets(["127.0.0.1:8081", "127.0.0.1:8082"]),
        config=IngressConfig(
            listen_address="127.0.0.1:9081",
            ready_path="/ready",
            webhook_path="/telegram/webhook",
        ),
    )

    assert "127.0.0.1:9081 {" in rendered
    assert rendered.count("to 127.0.0.1:8081") == 2
    assert rendered.count("to 127.0.0.1:8082") == 2
    assert "@upstream_ready path /ready" in rendered
    assert "@telegram_webhook path /telegram/webhook" in rendered
    assert "health_uri /ready" in rendered
    assert "unhealthy_status 5xx" in rendered


def test_parse_targets_rejects_duplicates() -> None:
    with pytest.raises(ValueError, match="duplicate replica target"):
        parse_targets(["127.0.0.1:8081", "127.0.0.1:8081"])


def test_render_caddyfile_requires_slash_prefixed_paths() -> None:
    with pytest.raises(ValueError, match="webhook_path must start with '/'"):
        render_caddyfile(
            parse_targets(["127.0.0.1:8081"]),
            config=IngressConfig(webhook_path="telegram/webhook"),
        )


def test_main_writes_rendered_file_from_targets_json(tmp_path) -> None:
    output_path = tmp_path / "Caddyfile.loadtest"

    exit_code = main(
        [
            "--targets-json",
            '["127.0.0.1:8081", "127.0.0.1:8082"]',
            "--listen-address",
            "127.0.0.1:9090",
            "--output",
            str(output_path),
        ]
    )

    assert exit_code == 0
    rendered = output_path.read_text(encoding="utf-8")
    assert "127.0.0.1:9090 {" in rendered
    assert rendered.count("reverse_proxy @") == 2


def test_main_prints_config_to_stdout(capsys) -> None:
    exit_code = main(["--target", "127.0.0.1:8081"])

    assert exit_code == 0
    captured = capsys.readouterr()
    assert "127.0.0.1:8081" in captured.out
    assert captured.err == ""


def test_main_dispatches_serve_mode(monkeypatch) -> None:
    async def fake_run(args) -> int:
        assert args.listen_port == 9080
        assert args.upstream_url == ["http://127.0.0.1:8081"]
        return 7

    monkeypatch.setattr("scripts.loadtest_ingress.run_ingress_server", fake_run)

    exit_code = main(["serve", "--upstream-url", "http://127.0.0.1:8081"])

    assert exit_code == 7


def test_parse_upstream_urls_reject_duplicates() -> None:
    with pytest.raises(ValueError, match="duplicate upstream URL"):
        parse_upstream_urls(["http://127.0.0.1:8081", "http://127.0.0.1:8081"])


@pytest.mark.asyncio
async def test_round_robin_upstreams_use_only_healthy_targets(unused_tcp_port_factory) -> None:
    async def ready(_request: web.Request) -> web.Response:
        return web.Response(text="ok")

    healthy_app = web.Application()
    healthy_app.router.add_get("/ready", ready)
    unhealthy_app = web.Application()

    async def unhealthy_ready(_request: web.Request) -> web.Response:
        return web.Response(status=503)

    unhealthy_app.router.add_get("/ready", unhealthy_ready)

    async def start_server(app: web.Application) -> tuple[web.AppRunner, str]:
        runner = web.AppRunner(app)
        await runner.setup()
        port = unused_tcp_port_factory()
        site = web.TCPSite(runner, host="127.0.0.1", port=port)
        await site.start()
        return runner, f"http://127.0.0.1:{port}"

    healthy_runner, healthy_url = await start_server(healthy_app)
    unhealthy_runner, unhealthy_url = await start_server(unhealthy_app)

    try:
        upstreams = parse_upstream_urls([healthy_url, unhealthy_url])
        state = RoundRobinUpstreams(upstreams, ready_path="/ready", health_timeout_seconds=1.0)

        from aiohttp import ClientSession

        async with ClientSession() as client:
            await state.refresh(client)
        chosen = await state.choose()

        assert chosen is not None
        assert chosen.base_url == healthy_url
    finally:
        await healthy_runner.cleanup()
        await unhealthy_runner.cleanup()
