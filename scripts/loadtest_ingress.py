from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from itertools import count
from pathlib import Path
import sys
from urllib.parse import urlsplit

from aiohttp import ClientError, ClientSession, ClientTimeout, TCPConnector, web


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_TEMPLATE_PATH = ROOT / "deploy" / "Caddyfile.loadtest.template"
DEFAULT_LISTEN_ADDRESS = "127.0.0.1:9080"
DEFAULT_INGRESS_HEALTH_PATH = "/health"
DEFAULT_READY_PATH = "/ready"
DEFAULT_WEBHOOK_PATH = "/telegram/webhook"
DEFAULT_LB_POLICY = "round_robin"
DEFAULT_LB_TRY_DURATION = "5s"
DEFAULT_LB_TRY_INTERVAL = "250ms"
DEFAULT_FAIL_DURATION = "10s"
DEFAULT_MAX_FAILS = 1
DEFAULT_UNHEALTHY_STATUS = "5xx"
DEFAULT_UPSTREAM_KEEPALIVE = "2m"
DEFAULT_UPSTREAM_KEEPALIVE_INTERVAL = "30s"
DEFAULT_UPSTREAM_TIMEOUT_SECONDS = 10.0
DEFAULT_UPSTREAM_CONNECTION_LIMIT = 0
DEFAULT_UPSTREAM_CONNECTION_LIMIT_PER_HOST = 0
DEFAULT_LISTEN_BACKLOG = 4096


@dataclass(frozen=True, slots=True)
class UpstreamTarget:
    dial_address: str


@dataclass(frozen=True, slots=True)
class IngressConfig:
    listen_address: str = DEFAULT_LISTEN_ADDRESS
    ingress_health_path: str = DEFAULT_INGRESS_HEALTH_PATH
    ready_path: str = DEFAULT_READY_PATH
    webhook_path: str = DEFAULT_WEBHOOK_PATH
    lb_policy: str = DEFAULT_LB_POLICY
    lb_try_duration: str = DEFAULT_LB_TRY_DURATION
    lb_try_interval: str = DEFAULT_LB_TRY_INTERVAL
    fail_duration: str = DEFAULT_FAIL_DURATION
    max_fails: int = DEFAULT_MAX_FAILS
    unhealthy_status: str = DEFAULT_UNHEALTHY_STATUS
    upstream_keepalive: str = DEFAULT_UPSTREAM_KEEPALIVE
    upstream_keepalive_interval: str = DEFAULT_UPSTREAM_KEEPALIVE_INTERVAL

    def validate(self) -> None:
        if not self.listen_address.strip():
            raise ValueError("listen address must not be empty")
        for field_name, value in (
            ("ingress_health_path", self.ingress_health_path),
            ("ready_path", self.ready_path),
            ("webhook_path", self.webhook_path),
        ):
            if not value.startswith("/"):
                raise ValueError(f"{field_name} must start with '/'")
        if self.max_fails < 1:
            raise ValueError("max_fails must be >= 1")
        if not self.unhealthy_status.strip():
            raise ValueError("unhealthy_status must not be empty")
        if not self.upstream_keepalive.strip():
            raise ValueError("upstream_keepalive must not be empty")
        if not self.upstream_keepalive_interval.strip():
            raise ValueError("upstream_keepalive_interval must not be empty")


@dataclass(frozen=True, slots=True)
class UpstreamUrl:
    base_url: str


def parse_upstream_target(raw: str) -> UpstreamTarget:
    candidate = raw.strip()
    if not candidate:
        raise ValueError("replica target must not be empty")
    if any(token in candidate for token in ("://", "/", "@", "?", "#")):
        raise ValueError("replica target must be host:port without scheme, path, query, or credentials")
    parsed = urlsplit(f"//{candidate}")
    if not parsed.hostname or parsed.port is None:
        raise ValueError("replica target must be host:port")
    host = parsed.hostname
    if ":" in host:
        host = f"[{host}]"
    return UpstreamTarget(dial_address=f"{host}:{parsed.port}")


def parse_targets(raw_targets: Sequence[str]) -> list[UpstreamTarget]:
    if not raw_targets:
        raise ValueError("at least one replica target is required")
    parsed_targets: list[UpstreamTarget] = []
    seen: set[str] = set()
    for raw_target in raw_targets:
        target = parse_upstream_target(raw_target)
        if target.dial_address in seen:
            raise ValueError(f"duplicate replica target: {target.dial_address}")
        seen.add(target.dial_address)
        parsed_targets.append(target)
    return parsed_targets


def parse_targets_json(raw_json: str) -> list[str]:
    payload = json.loads(raw_json)
    if not isinstance(payload, list) or not all(isinstance(item, str) for item in payload):
        raise ValueError("targets JSON must be an array of host:port strings")
    return list(payload)


def parse_upstream_url(raw: str) -> UpstreamUrl:
    parsed = urlsplit(raw.strip())
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("upstream URL must use http or https")
    if not parsed.netloc:
        raise ValueError("upstream URL must include host and port")
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise ValueError("upstream URL must not include path, query, or fragment")
    return UpstreamUrl(base_url=f"{parsed.scheme}://{parsed.netloc}")


def parse_upstream_urls(raw_urls: Sequence[str]) -> list[UpstreamUrl]:
    if not raw_urls:
        raise ValueError("at least one upstream URL is required")
    parsed_urls: list[UpstreamUrl] = []
    seen: set[str] = set()
    for raw_url in raw_urls:
        upstream = parse_upstream_url(raw_url)
        if upstream.base_url in seen:
            raise ValueError(f"duplicate upstream URL: {upstream.base_url}")
        seen.add(upstream.base_url)
        parsed_urls.append(upstream)
    return parsed_urls


def parse_upstream_urls_json(raw_json: str) -> list[str]:
    payload = json.loads(raw_json)
    if not isinstance(payload, list) or not all(isinstance(item, str) for item in payload):
        raise ValueError("upstream URLs JSON must be an array of URL strings")
    return list(payload)


def render_proxy_block(
    matcher_name: str,
    matcher_path: str,
    *,
    targets: Sequence[UpstreamTarget],
    config: IngressConfig,
) -> str:
    lines = [
        f"    @{matcher_name} path {matcher_path}",
        f"    handle @{matcher_name} {{",
        "        reverse_proxy {",
    ]
    lines.extend(f"            to {target.dial_address}" for target in targets)
    lines.extend(
        [
            f"            lb_policy {config.lb_policy}",
            f"            lb_try_duration {config.lb_try_duration}",
            f"            lb_try_interval {config.lb_try_interval}",
            f"            fail_duration {config.fail_duration}",
            f"            max_fails {config.max_fails}",
            f"            unhealthy_status {config.unhealthy_status}",
            "            transport http {",
            f"                keepalive {config.upstream_keepalive}",
            f"                keepalive_interval {config.upstream_keepalive_interval}",
            "            }",
            "        }",
            "    }",
        ]
    )
    return "\n".join(lines)


def render_caddyfile(
    targets: Sequence[UpstreamTarget],
    *,
    config: IngressConfig | None = None,
    template_path: Path = DEFAULT_TEMPLATE_PATH,
) -> str:
    normalized_config = config or IngressConfig()
    normalized_config.validate()
    if not targets:
        raise ValueError("at least one replica target is required")
    template = template_path.read_text(encoding="utf-8")
    proxy_blocks = "\n\n".join(
        [
            render_proxy_block(
                "upstream_ready",
                normalized_config.ready_path,
                targets=targets,
                config=normalized_config,
            ),
            render_proxy_block(
                "telegram_webhook",
                normalized_config.webhook_path,
                targets=targets,
                config=normalized_config,
            ),
        ]
    )
    rendered = template
    for token, value in {
        "LISTEN_ADDRESS": normalized_config.listen_address,
        "INGRESS_HEALTH_PATH": normalized_config.ingress_health_path,
        "PROXY_BLOCKS": proxy_blocks,
    }.items():
        rendered = rendered.replace(f"@@{token}@@", str(value))
    if "@@" in rendered:
        raise ValueError("unreplaced template placeholder remains in loadtest ingress template")
    if not rendered.endswith("\n"):
        rendered = f"{rendered}\n"
    return rendered


def build_config_from_args(args: argparse.Namespace) -> IngressConfig:
    return IngressConfig(
        listen_address=args.listen_address,
        ingress_health_path=args.ingress_health_path,
        ready_path=args.ready_path,
        webhook_path=args.webhook_path,
        lb_policy=args.lb_policy,
        lb_try_duration=args.lb_try_duration,
        lb_try_interval=args.lb_try_interval,
        fail_duration=args.fail_duration,
        max_fails=args.max_fails,
        unhealthy_status=args.unhealthy_status,
        upstream_keepalive=args.upstream_keepalive,
        upstream_keepalive_interval=args.upstream_keepalive_interval,
    )


def resolve_targets(args: argparse.Namespace) -> list[UpstreamTarget]:
    raw_targets = list(args.target)
    if args.targets_json:
        raw_targets.extend(parse_targets_json(args.targets_json))
    return parse_targets(raw_targets)


def resolve_upstream_urls(args: argparse.Namespace) -> list[UpstreamUrl]:
    raw_urls = list(args.upstream_url)
    if args.upstream_urls_json:
        raw_urls.extend(parse_upstream_urls_json(args.upstream_urls_json))
    return parse_upstream_urls(raw_urls)


class RoundRobinUpstreams:
    def __init__(
        self,
        upstreams: Sequence[UpstreamUrl],
        *,
        ready_path: str,
        health_timeout_seconds: float,
    ) -> None:
        self._upstreams = list(upstreams)
        self._ready_path = ready_path
        self._health_timeout_seconds = health_timeout_seconds
        self._healthy = {upstream.base_url: True for upstream in upstreams}
        self._counter = count()
        self._lock = asyncio.Lock()

    async def refresh(self, client: ClientSession) -> None:
        results = await asyncio.gather(
            *(self._probe(client, upstream) for upstream in self._upstreams),
            return_exceptions=True,
        )
        async with self._lock:
            for upstream, result in zip(self._upstreams, results, strict=True):
                self._healthy[upstream.base_url] = result is True

    async def choose(self) -> UpstreamUrl | None:
        async with self._lock:
            healthy = [upstream for upstream in self._upstreams if self._healthy.get(upstream.base_url, False)]
            if not healthy:
                return None
            index = next(self._counter) % len(healthy)
            return healthy[index]

    async def mark_unhealthy(self, upstream: UpstreamUrl) -> None:
        async with self._lock:
            self._healthy[upstream.base_url] = False

    async def _probe(self, client: ClientSession, upstream: UpstreamUrl) -> bool:
        try:
            async with client.get(
                f"{upstream.base_url}{self._ready_path}",
                timeout=ClientTimeout(total=self._health_timeout_seconds),
            ) as response:
                return response.status == 200
        except (ClientError, TimeoutError, OSError):
            return False


async def run_ingress_server(args: argparse.Namespace) -> int:
    _validate_ingress_args(args)
    upstreams = resolve_upstream_urls(args)
    state = RoundRobinUpstreams(
        upstreams,
        ready_path=args.ready_path,
        health_timeout_seconds=args.health_timeout_seconds,
    )
    client = _create_ingress_client(args)
    app = _create_ingress_app(args, state=state, client=client)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host=args.listen_host, port=args.listen_port, backlog=args.listen_backlog)
    health_task = asyncio.create_task(_health_loop(args, state=state, client=client), name="loadtest-ingress-health")
    try:
        await state.refresh(client)
        await site.start()
        await asyncio.Event().wait()
    finally:
        health_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await health_task
        await client.close()
        await runner.cleanup()


def _validate_ingress_args(args: argparse.Namespace) -> None:
    if args.upstream_connection_limit < 0:
        raise ValueError("upstream connection limit must be >= 0")
    if args.upstream_connection_limit_per_host < 0:
        raise ValueError("upstream connection limit per host must be >= 0")
    if args.listen_backlog < 1:
        raise ValueError("listen backlog must be >= 1")


def _create_ingress_client(args: argparse.Namespace) -> ClientSession:
    connector = TCPConnector(
        limit=args.upstream_connection_limit,
        limit_per_host=args.upstream_connection_limit_per_host,
        enable_cleanup_closed=True,
    )
    return ClientSession(
        timeout=ClientTimeout(total=args.upstream_timeout_seconds),
        connector=connector,
    )


def _create_ingress_app(
    args: argparse.Namespace,
    *,
    state: RoundRobinUpstreams,
    client: ClientSession,
) -> web.Application:
    app = web.Application()
    app["upstream_state"] = state
    app["upstream_client"] = client
    app.router.add_get(args.ingress_health_path, _ingress_health)
    app.router.add_route("*", args.ready_path, _proxy)
    app.router.add_route("*", args.webhook_path, _proxy)
    return app


async def _ingress_health(_request: web.Request) -> web.Response:
    return web.Response(text="ok", status=200)


async def _proxy(request: web.Request) -> web.Response:
    state: RoundRobinUpstreams = request.app["upstream_state"]
    client: ClientSession = request.app["upstream_client"]
    upstream = await state.choose()
    if upstream is None:
        return web.Response(text="no healthy upstreams", status=503)
    try:
        return await _proxy_to_upstream(request, client=client, upstream=upstream)
    except (ClientError, TimeoutError, OSError):
        await state.mark_unhealthy(upstream)
        return web.Response(text="upstream unavailable", status=503)


async def _proxy_to_upstream(
    request: web.Request,
    *,
    client: ClientSession,
    upstream: UpstreamUrl,
) -> web.Response:
    async with client.request(
        request.method,
        f"{upstream.base_url}{request.path_qs}",
        data=await request.read(),
        headers=_forwarded_headers(request),
        allow_redirects=False,
    ) as response:
        body = await response.read()
        return web.Response(status=response.status, headers=_response_headers(response), body=body)


async def _health_loop(args: argparse.Namespace, *, state: RoundRobinUpstreams, client: ClientSession) -> None:
    while True:
        await state.refresh(client)
        await asyncio.sleep(args.health_interval_seconds)


def _forwarded_headers(request: web.Request) -> dict[str, str]:
    headers = {key: value for key, value in request.headers.items() if key.lower() not in {"host", "content-length"}}
    headers["X-Forwarded-For"] = request.remote or "127.0.0.1"
    return headers


def _response_headers(response) -> dict[str, str]:
    return {
        key: value
        for key, value in response.headers.items()
        if key.lower() not in {"content-length", "transfer-encoding", "connection"}
    }


def build_render_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Render a Caddy ingress config for local multi-instance webhook load tests."
    )
    parser.add_argument(
        "--target",
        action="append",
        default=[],
        help="Replica host:port target. Repeat for each webhook replica.",
    )
    parser.add_argument(
        "--targets-json",
        help='JSON array of replica targets, for example ["127.0.0.1:8081", "127.0.0.1:8082"].',
    )
    parser.add_argument("--listen-address", default=DEFAULT_LISTEN_ADDRESS)
    parser.add_argument("--ingress-health-path", default=DEFAULT_INGRESS_HEALTH_PATH)
    parser.add_argument("--ready-path", default=DEFAULT_READY_PATH)
    parser.add_argument("--webhook-path", default=DEFAULT_WEBHOOK_PATH)
    parser.add_argument("--lb-policy", default=DEFAULT_LB_POLICY)
    parser.add_argument("--lb-try-duration", default=DEFAULT_LB_TRY_DURATION)
    parser.add_argument("--lb-try-interval", default=DEFAULT_LB_TRY_INTERVAL)
    parser.add_argument("--fail-duration", default=DEFAULT_FAIL_DURATION)
    parser.add_argument("--max-fails", type=int, default=DEFAULT_MAX_FAILS)
    parser.add_argument("--unhealthy-status", default=DEFAULT_UNHEALTHY_STATUS)
    parser.add_argument("--upstream-keepalive", default=DEFAULT_UPSTREAM_KEEPALIVE)
    parser.add_argument("--upstream-keepalive-interval", default=DEFAULT_UPSTREAM_KEEPALIVE_INTERVAL)
    parser.add_argument("--template", type=Path, default=DEFAULT_TEMPLATE_PATH)
    parser.add_argument("--output", type=Path, help="Write the rendered Caddyfile to this path.")
    return parser


def build_parser() -> argparse.ArgumentParser:
    """Backward-compatible render parser."""
    return build_render_parser()


def build_serve_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run a local HTTP load balancer for multi-instance webhook tests."
    )
    parser.add_argument("--listen-host", default="127.0.0.1")
    parser.add_argument("--listen-port", type=int, default=9080)
    parser.add_argument("--ingress-health-path", default=DEFAULT_INGRESS_HEALTH_PATH)
    parser.add_argument("--ready-path", default=DEFAULT_READY_PATH)
    parser.add_argument("--webhook-path", default=DEFAULT_WEBHOOK_PATH)
    parser.add_argument("--upstream-url", action="append", default=[])
    parser.add_argument("--upstream-urls-json")
    parser.add_argument("--health-interval-seconds", type=float, default=2.0)
    parser.add_argument("--health-timeout-seconds", type=float, default=2.0)
    parser.add_argument("--upstream-timeout-seconds", type=float, default=DEFAULT_UPSTREAM_TIMEOUT_SECONDS)
    parser.add_argument("--upstream-connection-limit", type=int, default=DEFAULT_UPSTREAM_CONNECTION_LIMIT)
    parser.add_argument(
        "--upstream-connection-limit-per-host",
        type=int,
        default=DEFAULT_UPSTREAM_CONNECTION_LIMIT_PER_HOST,
    )
    parser.add_argument("--listen-backlog", type=int, default=DEFAULT_LISTEN_BACKLOG)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "serve":
        parser = build_serve_parser()
        args = parser.parse_args(argv[1:])
        try:
            return asyncio.run(run_ingress_server(args))
        except ValueError as exc:
            parser.error(str(exc))

    parser = build_render_parser()
    args = parser.parse_args(argv)
    try:
        rendered = render_caddyfile(
            resolve_targets(args),
            config=build_config_from_args(args),
            template_path=args.template,
        )
    except ValueError as exc:
        parser.error(str(exc))
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
