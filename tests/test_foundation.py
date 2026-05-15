from __future__ import annotations

import inspect
import io
import logging
import os
from pathlib import Path

import pytest


def test_config_module_imports() -> None:
    from app.config import get_settings

    settings = get_settings()
    assert settings is not None


def test_app_main_imports() -> None:
    import app.main  # noqa: F401


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
async def test_health_check_returns_ok_response() -> None:
    from app.main import health_check

    response = await health_check(None)  # type: ignore[arg-type]
    assert response.status == 200
    assert b'"status": "ok"' in response.body


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
    settings = config_module.get_settings()
    assert settings.app_env.value == "staging"
