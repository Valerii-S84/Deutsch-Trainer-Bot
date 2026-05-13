from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppEnvironment(str, Enum):
    """Deployment environment."""

    production = "production"
    staging = "staging"
    development = "development"


class Settings(BaseSettings):
    """Environment-driven settings for production-ready deployment."""

    app_env: AppEnvironment = AppEnvironment.development
    app_name: str = "deutsch-trainer-bot"

    bot_token: Optional[SecretStr] = None
    telegram_webhook_url: Optional[str] = None
    telegram_webhook_secret: Optional[SecretStr] = None
    telegram_webhook_path: str = "/telegram/webhook"
    bot_webhook_enabled: bool = False
    bot_polling_enabled: bool = True
    bot_max_request_timeout: int = 30

    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/deutsch_trainer"
    redis_url: str = "redis://localhost:6379/0"

    quiz_bank_api_base_url: str = "https://api.quiz-bank.example.internal"
    quiz_bank_api_key: Optional[SecretStr] = None

    log_level: str = "INFO"

    plus_price_stars: Optional[str] = Field(default=None, alias="PLUS_PRICE_STARS")
    pro_price_stars: Optional[str] = Field(default=None, alias="PRO_PRICE_STARS")
    plus_duration_days: Optional[int] = Field(default=None, alias="PLUS_DURATION_DAYS")
    pro_duration_days: Optional[int] = Field(default=None, alias="PRO_DURATION_DAYS")
    tariff_public_copy: Optional[str] = Field(default=None, alias="TARIFF_PUBLIC_COPY")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="",
        extra="ignore",
        case_sensitive=False,
    )

    @field_validator("bot_max_request_timeout")
    @classmethod
    def validate_timeout(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("BOT_MAX_REQUEST_TIMEOUT must be > 0")
        return value

    @property
    def webhook_mode_enabled(self) -> bool:
        return bool(self.telegram_webhook_url and self.telegram_webhook_secret and self.bot_webhook_enabled)

    def require_production_secrets(self) -> None:
        """Fail fast when mandatory production settings are missing."""
        if self.app_env != AppEnvironment.production:
            return

        if not self.bot_token or not self.bot_token.get_secret_value():
            raise ValueError("BOT_TOKEN is required in production")
        if not self.telegram_webhook_secret or not self.telegram_webhook_secret.get_secret_value():
            raise ValueError("TELEGRAM_WEBHOOK_SECRET is required in production")
        if not self.telegram_webhook_url:
            raise ValueError("TELEGRAM_WEBHOOK_URL is required in production")
        if not self.quiz_bank_api_key or not self.quiz_bank_api_key.get_secret_value():
            raise ValueError("QUIZ_BANK_API_KEY is required in production")


def get_settings() -> Settings:
    """Load and validate environment configuration."""

    return Settings()  # type: ignore[call-arg]

