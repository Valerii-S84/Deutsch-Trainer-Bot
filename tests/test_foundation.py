from __future__ import annotations

import inspect
import io
import logging
import os
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from pydantic import SecretStr


def test_config_module_imports() -> None:
    from app.config import clear_settings_cache, get_settings

    clear_settings_cache()
    settings = get_settings()
    assert settings is not None
    assert get_settings() is settings


def test_app_main_imports() -> None:
    import app.main  # noqa: F401


def test_create_bot_uses_fake_session_when_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.main

    class FakeSettings:
        bot_fake_api_enabled = True

    monkeypatch.setattr(app.main, "get_settings", lambda: FakeSettings())

    bot = app.main.create_bot("123:ABCDEF")

    assert bot.session.__class__.__name__ == "FakeTelegramSession"


def test_db_session_imports() -> None:
    from app.db import session  # noqa: F401


def test_db_session_factory_is_async_context_manager() -> None:
    from app.db.session import get_session

    session_context = get_session()
    assert hasattr(session_context, "__aenter__")
    assert hasattr(session_context, "__aexit__")


def test_webhook_runtime_does_not_call_removed_aiogram_api() -> None:
    import app.main

    assert hasattr(app.main, "create_webhook_app")
    assert "start_webhook" not in inspect.getsource(app.main.run_bot)


@pytest.mark.asyncio
async def test_register_webhook_resets_and_sets_telegram_state() -> None:
    import app.main

    class FakeBot:
        def __init__(self) -> None:
            self.delete_webhook = AsyncMock()
            self.set_webhook = AsyncMock()

    bot = FakeBot()
    config = app.main.WebhookRuntimeConfig(
        url="https://example.test",
        path="/telegram/webhook",
        secret="test-secret",
        request_timeout=30,
        max_connections=40,
        handle_in_background=True,
    )

    await app.main.register_webhook(bot, config=config)

    bot.delete_webhook.assert_awaited_once_with(drop_pending_updates=True)
    bot.set_webhook.assert_awaited_once_with(
        url="https://example.test/telegram/webhook",
        secret_token="test-secret",
        request_timeout=30,
        max_connections=40,
    )


@pytest.mark.asyncio
async def test_run_bot_webhook_runtime_serves_without_registering(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.main

    class FakeBot:
        def __init__(self) -> None:
            self.session = type("Session", (), {"close": AsyncMock()})()

    class FakeSettings:
        def __init__(self) -> None:
            self.log_level = "INFO"
            self.bot_token = SecretStr("123:ABCDEF")
            self.telegram_webhook_url = "https://example.test"
            self.telegram_webhook_path = "/telegram/webhook"
            self.telegram_webhook_secret = SecretStr("secret-token")
            self.bot_max_request_timeout = 30
            self.telegram_webhook_max_connections = 40
            self.webhook_mode_enabled = True
            self.bot_polling_enabled = False

        def require_production_secrets(self) -> None:
            return None

    fake_settings = FakeSettings()
    fake_bot = FakeBot()
    run_webhook = AsyncMock()
    register_webhook = AsyncMock()
    close_redis = AsyncMock()
    dispose_engine = AsyncMock()

    monkeypatch.setattr(app.main, "get_settings", lambda: fake_settings)
    monkeypatch.setattr(app.main, "configure_logging", lambda _level: None)
    monkeypatch.setattr(app.main, "create_bot", lambda _token: fake_bot)
    monkeypatch.setattr(app.main, "create_dispatcher", lambda **_kwargs: object())
    monkeypatch.setattr(app.main, "run_webhook", run_webhook)
    monkeypatch.setattr(app.main, "register_webhook", register_webhook)
    monkeypatch.setattr(app.main, "_uses_redis_security_state", lambda _settings: False)
    monkeypatch.setattr(app.main, "close_redis_client", close_redis)
    monkeypatch.setattr(app.main, "dispose_engine", dispose_engine)

    await app.main.run_bot()

    run_webhook.assert_awaited_once()
    register_webhook.assert_not_awaited()
    fake_bot.session.close.assert_awaited_once()
    close_redis.assert_awaited_once_with(None)
    dispose_engine.assert_awaited_once()


@pytest.mark.asyncio
async def test_health_check_returns_ok_response() -> None:
    from app.main import health_check

    response = await health_check(None)  # type: ignore[arg-type]
    assert response.status == 200
    assert b'"status": "ok"' in response.body


@pytest.mark.asyncio
async def test_readiness_check_reports_db_and_redis(monkeypatch: pytest.MonkeyPatch) -> None:
    from aiohttp import web

    import app.main

    class FakeRedis:
        async def ping(self) -> bool:
            return True

    async def fake_pool_wait() -> float:
        return 1.25

    monkeypatch.setattr(app.main, "measure_pool_wait_ms", fake_pool_wait)
    application = web.Application()
    application["redis_client"] = FakeRedis()
    request = type("Request", (), {"app": application})()

    response = await app.main.readiness_check(request)  # type: ignore[arg-type]

    assert response.status == 200
    assert b'"status": "ok"' in response.body
    assert b'"pool_wait_ms": 1.25' in response.body


def test_logging_redacts_sensitive_values_for_child_loggers() -> None:
    from app.logging_config import configure_logging

    stream = io.StringIO()
    configure_logging("INFO")
    for handler in logging.getLogger().handlers:
        handler.stream = stream

    telegram_token = "1234567890:" + "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi"
    logging.getLogger("app.test").info(
        "token=dummy-token secret=hidden api-key=edge-key password=pwd "
        "authorization=Bearer auth-token, credential=runtime-credential "
        "database_url=postgresql://user:password@db/app %s, user_id=1",
        telegram_token,
    )

    output = stream.getvalue()
    assert "dummy-token" not in output
    assert "hidden" not in output
    assert "edge-key" not in output
    assert "auth-token" not in output
    assert "runtime-credential" not in output
    assert "postgresql://user:password@db/app" not in output
    assert telegram_token not in output
    assert "token=***" in output
    assert "authorization=***" in output
    assert "credential=***" in output
    assert "database_url=***" in output


def test_exception_summary_log_omits_traceback_and_exception_message(caplog: pytest.LogCaptureFixture) -> None:
    from app.logging_config import log_exception_summary

    logger = logging.getLogger("app.test.safe_summary")
    error = RuntimeError(
        "invoice_payload=dtbpay:1:secret "
        "telegram_payment_charge_id=tg-secret "
        "first_name=Anna"
    )

    with caplog.at_level(logging.ERROR, logger=logger.name):
        log_exception_summary(logger, "payment_confirmation_unexpected_failed", error, telegram_user_id=111)

    assert "payment_confirmation_unexpected_failed" in caplog.text
    assert "telegram_user_id=111" in caplog.text
    assert "error_type=RuntimeError" in caplog.text
    assert "Traceback" not in caplog.text
    assert "dtbpay:1:secret" not in caplog.text
    assert "tg-secret" not in caplog.text
    assert "Anna" not in caplog.text


def test_exception_summary_allows_level_context_key(caplog: pytest.LogCaptureFixture) -> None:
    from app.logging_config import log_exception_summary

    logger = logging.getLogger("app.test.safe_summary_context")

    with caplog.at_level(logging.ERROR, logger=logger.name):
        log_exception_summary(logger, "theme_training_open_unexpected_failed", RuntimeError("boom"), level="A1")

    assert "theme_training_open_unexpected_failed" in caplog.text
    assert "level=A1" in caplog.text
    assert "error_type=RuntimeError" in caplog.text
    assert caplog.records[0].levelno == logging.ERROR


def test_no_obvious_secret_placeholders_in_code() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    targets = [
        repo_root / "app" / "config.py",
        repo_root / "app" / "main.py",
        repo_root / "app" / "logging_config.py",
        repo_root / "Dockerfile",
    ]

    forbidden = ["changeme", "real_secret", "hardcoded_secret", "your_secret", "password123"]
    for path in targets:
        content = path.read_text(encoding="utf-8").lower()
        for item in forbidden:
            assert item not in content


def test_env_example_contains_placeholders() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    env_example = (repo_root / ".env.example").read_text(encoding="utf-8")
    assert "<" in env_example and ">" in env_example
    assert "postgres-password" in env_example


def test_config_loads_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "staging")
    monkeypatch.setenv("BOT_TOKEN", "123:ABCDEF")
    monkeypatch.setenv("TELEGRAM_WEBHOOK_URL", "https://example.com")
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "webhook-secret")
    monkeypatch.setenv("QUIZ_BANK_API_KEY", "quiz-key")

    # force reload of module-level settings
    import importlib

    config_module = importlib.reload(__import__("app.config", fromlist=["get_settings"]))
    config_module.clear_settings_cache()
    settings = config_module.get_settings()
    assert settings.app_env.value == "staging"
