from __future__ import annotations

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

