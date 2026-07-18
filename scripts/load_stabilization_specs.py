from __future__ import annotations



from scripts import load_stabilization_orchestrator as _root
globals().update({name: value for name, value in vars(_root).items() if not name.startswith("__")})


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
        answer_worker=None if spec.answer_worker is None else clone_service_spec(spec.answer_worker),
        outbox_worker=None if spec.outbox_worker is None else clone_service_spec(spec.outbox_worker),
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


def _default_app_service() -> ServiceSpec:
    return ServiceSpec(
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
    )


def _default_worker_service() -> ServiceSpec:
    return ServiceSpec(
        runner="docker",
        replicas=1,
        command=["python", "-m", "app.workers.run_outbox"],
        env={
            "SECURITY_STATE_BACKEND": "redis",
            "SECURITY_RATE_LIMIT_ENABLED": "True",
            "BOT_FAKE_API_ENABLED": "True",
        },
        build=DockerBuildSpec(context="."),
    )


def _default_ingress_service() -> ServiceSpec:
    return ServiceSpec(
        runner="process",
        replicas=1,
        command=[
            "{python}", "scripts/loadtest_ingress.py", "serve", "--listen-host",
            "127.0.0.1", "--listen-port", "{listen_port}", "--ingress-health-path",
            "/health", "--ready-path", "{app_ready_path}", "--webhook-path",
            "{webhook_path}", "--upstream-urls-json", "{app_replica_urls_json}",
        ],
        listen_port=9080,
        ready_path="/health",
    )


def _default_stack_spec() -> WebhookStackSpec:
    return WebhookStackSpec(
        mode="webhook_multi_instance",
        webhook_path="/telegram/webhook",
        webhook_secret="loadtest-webhook-secret",
        app=_default_app_service(),
        worker=_default_worker_service(),
        ingress=_default_ingress_service(),
    )


def _stack_service_defaults(
    raw: Mapping[str, Any], base: WebhookStackSpec,
) -> tuple[ServiceSpec, ServiceSpec, ServiceSpec | None, ServiceSpec | None]:
    services = [
        clone_service_spec(base.app),
        clone_service_spec(base.worker),
        None if base.answer_worker is None else clone_service_spec(base.answer_worker),
        None if base.outbox_worker is None else clone_service_spec(base.outbox_worker),
    ]
    shared_image = raw.get("image")
    shared_build = build_spec_from_raw(raw.get("build"), base.app.build or base.worker.build)
    for service in services:
        if service is None:
            continue
        if shared_image is not None:
            service.image = str(shared_image)
        if shared_build is not None:
            service.build = clone_build_spec(shared_build)
    replica_keys = ("app_replicas", "worker_replicas", "answer_worker_replicas", "outbox_worker_replicas")
    for service, key in zip(services, replica_keys, strict=True):
        if service is not None:
            service.replicas = int(raw.get(key, service.replicas))
    return services[0], services[1], services[2], services[3]


def _resolve_ingress(raw: Any, default: ServiceSpec | None) -> ServiceSpec | None:
    if raw is False:
        return None
    if not isinstance(raw, Mapping):
        return default
    fallback = default or ServiceSpec(
        runner="process", replicas=1, command=[], listen_port=8081, ready_path="/health",
    )
    return service_spec_from_raw(raw, fallback)


def _resolve_side_worker(
    raw: Any,
    default: ServiceSpec | None,
    worker: ServiceSpec,
    replicas: int,
    module: str,
) -> ServiceSpec | None:
    if raw is False:
        return None
    if not isinstance(raw, Mapping):
        return default
    fallback = default or ServiceSpec(
        runner=worker.runner,
        replicas=replicas,
        command=["python", "-m", module],
        env=dict(worker.env),
        image=worker.image,
        build=clone_build_spec(worker.build),
        workdir=worker.workdir,
        extra_args=list(worker.extra_args),
    )
    return service_spec_from_raw(raw, fallback)


def _worker_replica_count(stack: WebhookStackSpec) -> int:
    return stack.worker.replicas + sum(
        service.replicas for service in (stack.answer_worker, stack.outbox_worker) if service is not None
    )


def _configure_stack_environment(stack: WebhookStackSpec) -> None:
    worker_count = _worker_replica_count(stack)
    app_defaults = {
        "BOT_WEBHOOK_ENABLED": "True", "BOT_FAKE_API_ENABLED": "True",
        "BOT_POLLING_ENABLED": "False", "TELEGRAM_WEBHOOK_HANDLE_IN_BACKGROUND": "False",
        "TELEGRAM_WEBHOOK_REQUIRE_HTTPS": "False", "WEBHOOK_INGRESS_BACKEND": "redis_stream",
        "TRAINING_ANSWER_CACHE_ENABLED": "True", "TELEGRAM_WEBHOOK_URL": "http://loadtest.local",
        "DB_APP_REPLICA_COUNT": str(stack.app.replicas), "DB_WORKER_REPLICA_COUNT": str(worker_count),
        "SECURITY_STATE_BACKEND": "redis", "SECURITY_RATE_LIMIT_ENABLED": "True",
    }
    for key, value in app_defaults.items():
        stack.app.env.setdefault(key, value)
    stack.app.env["TELEGRAM_WEBHOOK_SECRET"] = stack.webhook_secret
    stack.app.env["TELEGRAM_WEBHOOK_PATH"] = stack.webhook_path
    worker_defaults = {
        "DB_APP_REPLICA_COUNT": str(stack.app.replicas), "DB_WORKER_REPLICA_COUNT": str(worker_count),
        "SECURITY_STATE_BACKEND": "redis", "SECURITY_RATE_LIMIT_ENABLED": "True",
        "WEBHOOK_INGRESS_BACKEND": "redis_stream", "TRAINING_ANSWER_CACHE_ENABLED": "True",
        "BOT_FAKE_API_ENABLED": "True",
    }
    for service in (stack.worker, stack.answer_worker, stack.outbox_worker):
        if service is None:
            continue
        for key, value in worker_defaults.items():
            service.env.setdefault(key, value)
    for service in (stack.answer_worker, stack.outbox_worker):
        if service is not None:
            service.env.setdefault("TRAINING_ANSWER_WRITE_BEHIND_ENABLED", "True")


def merge_stack_spec(raw: Any, default: WebhookStackSpec | None) -> WebhookStackSpec | None:
    if raw is None:
        return clone_stack_spec(default)
    if not isinstance(raw, Mapping):
        raise ValueError("stack must be an object")
    base = clone_stack_spec(default) or _default_stack_spec()
    app, worker, answer_default, outbox_default = _stack_service_defaults(raw, base)
    ingress_default = None if base.ingress is None else clone_service_spec(base.ingress)
    stack = WebhookStackSpec(
        mode=str(raw.get("mode", base.mode)),
        webhook_path=str(raw.get("webhook_path", base.webhook_path)),
        webhook_secret=str(raw.get("webhook_secret", base.webhook_secret)),
        app=service_spec_from_raw(raw.get("app"), app),
        worker=service_spec_from_raw(raw.get("worker"), worker),
        answer_worker=_resolve_side_worker(
            raw.get("answer_worker"), answer_default, worker,
            int(raw.get("answer_worker_replicas", 1)), "app.workers.run_answer_persistence",
        ),
        outbox_worker=_resolve_side_worker(
            raw.get("outbox_worker"), outbox_default, worker,
            int(raw.get("outbox_worker_replicas", 1)), "app.workers.run_outbox",
        ),
        ingress=_resolve_ingress(raw.get("ingress"), ingress_default),
    )
    _configure_stack_environment(stack)
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
    seed_session_count = _root._seed_session_count(
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
