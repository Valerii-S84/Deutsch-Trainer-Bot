from __future__ import annotations

from scripts import load_stabilization_orchestrator as _root
globals().update({name: value for name, value in vars(_root).items() if not name.startswith("__")})


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
    _configure_webhook_load_parser(webhook_load_parser)
    return parser


def _configure_webhook_load_parser(webhook_load_parser: argparse.ArgumentParser) -> None:
    webhook_load_parser.add_argument("--base-url", required=True)
    webhook_load_parser.add_argument("--base-urls-csv", default="")
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
    webhook_load_parser.add_argument("--warmup-connections", type=int, default=0)
    webhook_load_parser.add_argument("--warmup-path", default="/health")
    webhook_load_parser.add_argument("--client-shards", type=int, default=1)
    webhook_load_parser.add_argument("--start-at-epoch-ms", type=float)
    webhook_load_parser.add_argument("--emit-samples", action="store_true")
    webhook_load_parser.add_argument("--start-update-id", type=int, default=1_000_000)
    webhook_load_parser.add_argument("--base-user-id", type=int, default=7_000_000_000)
    webhook_load_parser.add_argument("--pgbouncer-sample-output")
    webhook_load_parser.add_argument("--pgbouncer-sample-interval-ms", type=float, default=250.0)
    webhook_load_parser.add_argument("--postgres-lock-sample-output")
    webhook_load_parser.add_argument("--postgres-lock-sample-interval-ms", type=float, default=500.0)
    webhook_load_parser.add_argument(
        "--sampler-query-timeout-seconds",
        type=float,
        default=DEFAULT_SAMPLER_QUERY_TIMEOUT_SECONDS,
    )
    webhook_load_parser.add_argument(
        "--sampler-stop-timeout-seconds",
        type=float,
        default=DEFAULT_SAMPLER_STOP_TIMEOUT_SECONDS,
    )
    webhook_load_parser.add_argument("--validate-events", action="store_true")
    webhook_load_parser.add_argument("--queue-drain-timeout-seconds", type=float, default=120.0)
    webhook_load_parser.add_argument("--queue-drain-poll-interval-seconds", type=float, default=0.5)
    webhook_load_parser.add_argument("--webhook-ingress-stream-key", default="dtb:webhook_ingress:updates")
    webhook_load_parser.add_argument("--webhook-ingress-dead-letter-key", default="dtb:webhook_ingress:dead")
    webhook_load_parser.add_argument("--webhook-ingress-metrics-key-prefix", default="dtb:webhook_ingress:metrics")
    webhook_load_parser.add_argument("--answer-persist-stream-key", default="dtb:answer_persist:events")
    webhook_load_parser.add_argument("--answer-persist-dead-letter-key", default="dtb:answer_persist:dead")
    webhook_load_parser.add_argument("--answer-persist-metrics-key-prefix", default="dtb:answer_persist:metrics")
    webhook_load_parser.add_argument("--max-http-p95-ms", type=float, default=500.0)
    webhook_load_parser.add_argument("--max-http-p99-ms", type=float, default=1500.0)
    webhook_load_parser.add_argument("--max-processing-lag-p95-ms", type=float, default=3000.0)
    webhook_load_parser.add_argument("--telegram-timeout-ms", type=float, default=30000.0)
    webhook_load_parser.set_defaults(func=webhook_load)


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    result = args.func(args)
    if asyncio.iscoroutine(result):
        _install_uvloop_if_available()
        result = asyncio.run(result)
    raise SystemExit(result)


def _install_uvloop_if_available() -> None:
    try:
        import uvloop
    except ImportError:
        return
    uvloop.install()
