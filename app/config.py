from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import Field, SecretStr, field_validator, model_validator
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
    quiz_bank_edge_api_key: Optional[SecretStr] = None
    quiz_bank_consumer_id: Optional[str] = None
    quiz_bank_consumer_api_key: Optional[SecretStr] = None
    quiz_bank_timeout_seconds: int = 3
    quiz_bank_max_retries: int = 2
    # Deprecated compatibility alias from previous milestones:
    # do not remove because tests and legacy scripts still reference it.
    quiz_bank_api_key: Optional[SecretStr] = None

    log_level: str = "INFO"

    plus_price_stars: Optional[str] = Field(default=None, alias="PLUS_PRICE_STARS")
    pro_price_stars: Optional[str] = Field(default=None, alias="PRO_PRICE_STARS")
    plus_duration_days: Optional[int] = Field(default=None, alias="PLUS_DURATION_DAYS")
    pro_duration_days: Optional[int] = Field(default=None, alias="PRO_DURATION_DAYS")
    tariff_public_copy: Optional[str] = Field(default=None, alias="TARIFF_PUBLIC_COPY")
    free_daily_question_limit: int = Field(default=5, alias="FREE_DAILY_QUESTION_LIMIT")
    plus_daily_question_limit: int = Field(default=25, alias="PLUS_DAILY_QUESTION_LIMIT")
    pro_daily_question_limit: int = Field(default=100, alias="PRO_DAILY_QUESTION_LIMIT")

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

    @field_validator("quiz_bank_timeout_seconds")
    @classmethod
    def validate_quiz_bank_timeout(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("QUIZ_BANK_TIMEOUT_SECONDS must be > 0")
        return value

    @field_validator("quiz_bank_max_retries")
    @classmethod
    def validate_quiz_bank_retries(cls, value: int) -> int:
        if value < 0:
            raise ValueError("QUIZ_BANK_MAX_RETRIES must be >= 0")
        return value

    @field_validator("free_daily_question_limit", "plus_daily_question_limit", "pro_daily_question_limit")
    @classmethod
    def validate_daily_limit(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("Daily question limits must be > 0")
        return value

    @model_validator(mode="after")
    def validate_limit_hierarchy(self) -> "Settings":
        if not (
            self.free_daily_question_limit
            < self.plus_daily_question_limit
            < self.pro_daily_question_limit
        ):
            raise ValueError("Daily question limits must satisfy Free < Plus < Pro")
        return self

    @property
    def webhook_mode_enabled(self) -> bool:
        return bool(self.telegram_webhook_url and self.telegram_webhook_secret and self.bot_webhook_enabled)

    @property
    def quiz_bank_edge_api_key_or_legacy(self) -> Optional[str]:
        primary = self.quiz_bank_edge_api_key.get_secret_value() if self.quiz_bank_edge_api_key else None
        legacy = self.quiz_bank_api_key.get_secret_value() if self.quiz_bank_api_key else None
        return primary or legacy

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
        if not self.quiz_bank_edge_api_key_or_legacy:
            raise ValueError("QUIZ_BANK_EDGE_API_KEY (or QUIZ_BANK_API_KEY legacy) is required in production")
        if not self.quiz_bank_consumer_api_key or not self.quiz_bank_consumer_api_key.get_secret_value():
            raise ValueError("QUIZ_BANK_CONSUMER_API_KEY is required in production")
        if not self.quiz_bank_consumer_id:
            raise ValueError("QUIZ_BANK_CONSUMER_ID is required in production")


def get_settings() -> Settings:
    """Load and validate environment configuration."""

    return Settings()  # type: ignore[call-arg]
