from __future__ import annotations

from enum import Enum
from functools import lru_cache
from typing import Optional

from pydantic import Field, SecretStr, ValidationInfo, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppEnvironment(str, Enum):
    """Deployment environment."""

    production = "production"
    staging = "staging"
    development = "development"


class DbConnectionBackend(str, Enum):
    """Database connection strategy for async SQLAlchemy engines."""

    direct = "direct"
    pgbouncer_transaction = "pgbouncer_transaction"


class WebhookIngressBackend(str, Enum):
    """Telegram webhook delivery strategy."""

    direct = "direct"
    redis_stream = "redis_stream"


class _SettingsFields(BaseSettings):
    """Environment-driven settings for production-ready deployment."""

    app_env: AppEnvironment = AppEnvironment.development
    app_name: str = "deutsch-trainer-bot"

    bot_token: Optional[SecretStr] = None
    telegram_webhook_url: Optional[str] = None
    telegram_webhook_secret: Optional[SecretStr] = None
    telegram_webhook_path: str = "/telegram/webhook"
    telegram_webhook_require_https: bool = True
    telegram_webhook_max_connections: int = 40
    telegram_duplicate_update_ttl_seconds: int = 300
    bot_webhook_enabled: bool = False
    bot_polling_enabled: bool = True
    bot_fake_api_enabled: bool = False
    bot_max_request_timeout: int = 30
    telegram_webhook_handle_in_background: bool = True
    webhook_ingress_backend: WebhookIngressBackend = Field(
        default=WebhookIngressBackend.direct,
        alias="WEBHOOK_INGRESS_BACKEND",
    )
    webhook_ingress_stream_key: str = Field(
        default="dtb:webhook_ingress:updates",
        alias="WEBHOOK_INGRESS_STREAM_KEY",
    )
    webhook_ingress_group_name: str = Field(
        default="dtb-webhook-workers",
        alias="WEBHOOK_INGRESS_GROUP_NAME",
    )
    webhook_ingress_dead_letter_key: str = Field(
        default="dtb:webhook_ingress:dead",
        alias="WEBHOOK_INGRESS_DEAD_LETTER_KEY",
    )
    webhook_ingress_dedupe_key_prefix: str = Field(
        default="dtb:webhook_ingress:dedupe",
        alias="WEBHOOK_INGRESS_DEDUPE_KEY_PREFIX",
    )
    webhook_ingress_metrics_key_prefix: str = Field(
        default="dtb:webhook_ingress:metrics",
        alias="WEBHOOK_INGRESS_METRICS_KEY_PREFIX",
    )
    webhook_ingress_max_attempts: int = Field(default=5, alias="WEBHOOK_INGRESS_MAX_ATTEMPTS")
    webhook_ingress_worker_batch_size: int = Field(default=50, alias="WEBHOOK_INGRESS_WORKER_BATCH_SIZE")
    webhook_ingress_worker_parallelism: int = Field(default=20, alias="WEBHOOK_INGRESS_WORKER_PARALLELISM")
    webhook_ingress_read_block_ms: int = Field(default=1000, alias="WEBHOOK_INGRESS_READ_BLOCK_MS")
    webhook_ingress_enqueue_batch_size: int = Field(default=250, alias="WEBHOOK_INGRESS_ENQUEUE_BATCH_SIZE")
    webhook_ingress_enqueue_flush_interval_ms: int = Field(
        default=2,
        alias="WEBHOOK_INGRESS_ENQUEUE_FLUSH_INTERVAL_MS",
    )
    webhook_ingress_ack_before_redis: bool = Field(default=False, alias="WEBHOOK_INGRESS_ACK_BEFORE_REDIS")
    webhook_ingress_fast_answer_path: bool = Field(default=False, alias="WEBHOOK_INGRESS_FAST_ANSWER_PATH")
    webhook_ingress_stale_idle_ms: int = Field(default=60000, alias="WEBHOOK_INGRESS_STALE_IDLE_MS")
    webhook_ingress_processing_lag_sample_size: int = Field(
        default=10000,
        alias="WEBHOOK_INGRESS_PROCESSING_LAG_SAMPLE_SIZE",
    )
    webhook_ingress_queue_lag_unhealthy_ms: int = Field(
        default=120000,
        alias="WEBHOOK_INGRESS_QUEUE_LAG_UNHEALTHY_MS",
    )
    bot_global_in_flight_limit: int = 512
    bot_global_in_flight_timeout_seconds: float = 0.05
    security_rate_limit_enabled: bool = True
    security_state_backend: str = Field(default="auto", alias="SECURITY_STATE_BACKEND")

    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/deutsch_trainer"
    db_connection_backend: DbConnectionBackend = Field(
        default=DbConnectionBackend.direct,
        alias="DB_CONNECTION_BACKEND",
    )
    db_pgbouncer_max_client_conn: int = Field(default=200, alias="DB_PGBOUNCER_MAX_CLIENT_CONN")
    db_pgbouncer_client_headroom: int = Field(default=32, alias="DB_PGBOUNCER_CLIENT_HEADROOM")
    db_pgbouncer_reuse_app_connections: bool = Field(
        default=False,
        alias="DB_PGBOUNCER_REUSE_APP_CONNECTIONS",
    )
    db_app_replica_count: int = Field(default=1, alias="DB_APP_REPLICA_COUNT")
    db_worker_replica_count: int = Field(default=0, alias="DB_WORKER_REPLICA_COUNT")
    db_worker_client_budget_per_replica: int = Field(
        default=5,
        alias="DB_WORKER_CLIENT_BUDGET_PER_REPLICA",
    )
    db_pool_size: int = Field(default=20, alias="DB_POOL_SIZE")
    db_max_overflow: int = Field(default=10, alias="DB_MAX_OVERFLOW")
    db_pool_timeout: float = Field(default=5.0, alias="DB_POOL_TIMEOUT")
    db_pool_recycle: int = Field(default=1800, alias="DB_POOL_RECYCLE")
    db_pool_pre_ping: bool = Field(default=True, alias="DB_POOL_PRE_PING")
    worker_db_pool_size: int = Field(default=10, alias="WORKER_DB_POOL_SIZE")
    worker_db_max_overflow: int = Field(default=5, alias="WORKER_DB_MAX_OVERFLOW")
    worker_db_pool_timeout: float = Field(default=5.0, alias="WORKER_DB_POOL_TIMEOUT")
    redis_url: str = "redis://localhost:6379/0"
    redis_max_connections: int = Field(default=256, alias="REDIS_MAX_CONNECTIONS")
    redis_pool_timeout_seconds: float = Field(default=2.0, alias="REDIS_POOL_TIMEOUT_SECONDS")
    redis_warmup_connections: int = Field(default=0, alias="REDIS_WARMUP_CONNECTIONS")
    training_answer_cache_enabled: bool = Field(default=False, alias="TRAINING_ANSWER_CACHE_ENABLED")
    training_answer_cache_ttl_seconds: int = Field(default=600, alias="TRAINING_ANSWER_CACHE_TTL_SECONDS")
    training_answer_write_behind_enabled: bool = Field(
        default=False,
        alias="TRAINING_ANSWER_WRITE_BEHIND_ENABLED",
    )
    answer_persist_stream_key: str = Field(default="dtb:answer_persist:events", alias="ANSWER_PERSIST_STREAM_KEY")
    answer_persist_group_name: str = Field(
        default="dtb-answer-persist-workers",
        alias="ANSWER_PERSIST_GROUP_NAME",
    )
    answer_persist_dead_letter_key: str = Field(
        default="dtb:answer_persist:dead",
        alias="ANSWER_PERSIST_DEAD_LETTER_KEY",
    )
    answer_persist_event_key_prefix: str = Field(
        default="dtb:answer_persist:event",
        alias="ANSWER_PERSIST_EVENT_KEY_PREFIX",
    )
    answer_persist_question_key_prefix: str = Field(
        default="dtb:answer_persist:question",
        alias="ANSWER_PERSIST_QUESTION_KEY_PREFIX",
    )
    answer_persist_result_key_prefix: str = Field(
        default="dtb:answer_persist:result",
        alias="ANSWER_PERSIST_RESULT_KEY_PREFIX",
    )
    answer_persist_metrics_key_prefix: str = Field(
        default="dtb:answer_persist:metrics",
        alias="ANSWER_PERSIST_METRICS_KEY_PREFIX",
    )
    answer_persist_batch_size: int = Field(default=250, alias="ANSWER_PERSIST_BATCH_SIZE")
    answer_persist_flush_interval_ms: int = Field(default=100, alias="ANSWER_PERSIST_FLUSH_INTERVAL_MS")
    answer_persist_max_attempts: int = Field(default=5, alias="ANSWER_PERSIST_MAX_ATTEMPTS")
    answer_persist_stale_idle_ms: int = Field(default=60000, alias="ANSWER_PERSIST_STALE_IDLE_MS")
    answer_persist_processing_lag_sample_size: int = Field(
        default=10000,
        alias="ANSWER_PERSIST_PROCESSING_LAG_SAMPLE_SIZE",
    )

    quiz_bank_api_base_url: str = "https://api.quiz-bank.example.internal"
    quiz_bank_edge_api_key: Optional[SecretStr] = None
    quiz_bank_consumer_id: Optional[str] = None
    quiz_bank_consumer_api_key: Optional[SecretStr] = None
    quiz_bank_timeout_seconds: int = 3
    quiz_bank_max_retries: int = 2
    # Deprecated compatibility alias from previous milestones:
    # do not remove because tests and legacy scripts still reference it.
    quiz_bank_api_key: Optional[SecretStr] = None

    active_catalog_id: Optional[str] = Field(default=None, alias="ACTIVE_CATALOG_ID")
    catalog_source_path: str = Field(default="ProductionQuizBank", alias="CATALOG_SOURCE_PATH")
    catalog_import_dry_run: bool = Field(default=False, alias="CATALOG_IMPORT_DRY_RUN")
    enabled_cefr_levels: tuple[str, ...] = Field(default=("A1", "A2", "B1", "B2", "C1"), alias="ENABLED_CEFR_LEVELS")
    local_catalog_cache_enabled: bool = Field(default=False, alias="LOCAL_CATALOG_CACHE_ENABLED")
    local_catalog_cache_ttl_seconds: int = Field(default=15, alias="LOCAL_CATALOG_CACHE_TTL_SECONDS")

    log_level: str = "INFO"

    telegram_stars_mode: str = Field(default="test", alias="TELEGRAM_STARS_MODE")
    plus_price_stars: Optional[str] = Field(default="10", alias="PLUS_PRICE_STARS")
    pro_price_stars: Optional[str] = Field(default="20", alias="PRO_PRICE_STARS")
    plus_duration_days: Optional[int] = Field(default=30, alias="PLUS_DURATION_DAYS")
    pro_duration_days: Optional[int] = Field(default=90, alias="PRO_DURATION_DAYS")
    tariff_public_copy: str = Field(
        default=(
            "Plus: mehr Uebungen pro Tag, vollstaendiger Fortschritt und "
            "gezielte Fehlerwiederholung. Pro: erweiterte Statistik, mehr "
            "Training und tieferer Fehlerueberblick."
        ),
        alias="TARIFF_PUBLIC_COPY",
    )
    paywall_cooldown_policy: str = Field(default="none", alias="PAYWALL_COOLDOWN_POLICY")
    admin_telegram_user_ids: tuple[int, ...] = Field(default_factory=tuple, alias="ADMIN_TELEGRAM_USER_IDS")
    free_daily_question_limit: int = Field(default=5, alias="FREE_DAILY_QUESTION_LIMIT")
    plus_daily_question_limit: int = Field(default=25, alias="PLUS_DAILY_QUESTION_LIMIT")
    pro_daily_question_limit: int = Field(default=100, alias="PRO_DAILY_QUESTION_LIMIT")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="",
        extra="ignore",
        case_sensitive=False,
    )

class _SettingsValidation(_SettingsFields):
    @field_validator(
        "bot_max_request_timeout",
        "telegram_duplicate_update_ttl_seconds",
        "quiz_bank_timeout_seconds",
        "bot_global_in_flight_limit",
        "webhook_ingress_max_attempts",
        "webhook_ingress_worker_batch_size",
        "webhook_ingress_worker_parallelism",
        "webhook_ingress_read_block_ms",
        "webhook_ingress_enqueue_batch_size",
        "webhook_ingress_enqueue_flush_interval_ms",
        "webhook_ingress_stale_idle_ms",
        "webhook_ingress_processing_lag_sample_size",
        "webhook_ingress_queue_lag_unhealthy_ms",
        "db_pgbouncer_max_client_conn",
        "db_app_replica_count",
        "db_worker_client_budget_per_replica",
        "db_pool_size",
        "db_pool_timeout",
        "worker_db_pool_size",
        "worker_db_pool_timeout",
        "redis_max_connections",
        "redis_pool_timeout_seconds",
        "training_answer_cache_ttl_seconds",
        "answer_persist_batch_size",
        "answer_persist_flush_interval_ms",
        "answer_persist_max_attempts",
        "answer_persist_stale_idle_ms",
        "answer_persist_processing_lag_sample_size",
        "local_catalog_cache_ttl_seconds",
    )
    @classmethod
    def validate_positive_number(cls, value: int | float, info: ValidationInfo) -> int | float:
        if value <= 0:
            raise ValueError(f"{_env_name(info.field_name)} must be > 0")
        return value

    @field_validator("telegram_webhook_max_connections")
    @classmethod
    def validate_webhook_max_connections(cls, value: int) -> int:
        if value < 1 or value > 100:
            raise ValueError("TELEGRAM_WEBHOOK_MAX_CONNECTIONS must be between 1 and 100")
        return value

    @field_validator(
        "bot_global_in_flight_timeout_seconds",
        "db_pgbouncer_client_headroom",
        "db_worker_replica_count",
        "db_max_overflow",
        "worker_db_max_overflow",
        "quiz_bank_max_retries",
        "redis_warmup_connections",
    )
    @classmethod
    def validate_non_negative_number(cls, value: int | float, info: ValidationInfo) -> int | float:
        if value < 0:
            raise ValueError(f"{_env_name(info.field_name)} must be >= 0")
        return value

    @field_validator("db_pool_recycle")
    @classmethod
    def validate_db_pool_recycle(cls, value: int) -> int:
        if value < -1:
            raise ValueError("DB_POOL_RECYCLE must be -1 or >= 0")
        return value

    @field_validator("active_catalog_id")
    @classmethod
    def validate_active_catalog_id(cls, value: str | None) -> str | None:
        if value is None:
            return value
        normalized = value.strip()
        if not normalized:
            raise ValueError("ACTIVE_CATALOG_ID cannot be blank when set")
        return normalized

    @field_validator("catalog_source_path")
    @classmethod
    def validate_catalog_source_path(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("CATALOG_SOURCE_PATH cannot be blank")
        return normalized

    @field_validator("enabled_cefr_levels", mode="before")
    @classmethod
    def parse_enabled_cefr_levels(cls, value: object) -> tuple[str, ...]:
        if isinstance(value, str):
            raw_values = [item.strip().upper() for item in value.split(",") if item.strip()]
        else:
            raw_values = [str(item).strip().upper() for item in value]  # type: ignore[arg-type]
        allowed = {"A1", "A2", "B1", "B2", "C1", "C2"}
        levels = tuple(raw_values)
        if not levels:
            raise ValueError("ENABLED_CEFR_LEVELS must contain at least one level")
        if any(level not in allowed for level in levels):
            raise ValueError("ENABLED_CEFR_LEVELS supports only A1,A2,B1,B2,C1,C2")
        return levels

    @field_validator("security_state_backend")
    @classmethod
    def validate_security_state_backend(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"auto", "in_memory", "redis"}:
            raise ValueError("SECURITY_STATE_BACKEND must be auto, in_memory, or redis")
        return normalized

    @field_validator(
        "webhook_ingress_stream_key",
        "webhook_ingress_group_name",
        "webhook_ingress_dead_letter_key",
        "webhook_ingress_dedupe_key_prefix",
        "webhook_ingress_metrics_key_prefix",
        "answer_persist_stream_key",
        "answer_persist_group_name",
        "answer_persist_dead_letter_key",
        "answer_persist_event_key_prefix",
        "answer_persist_question_key_prefix",
        "answer_persist_result_key_prefix",
        "answer_persist_metrics_key_prefix",
    )
    @classmethod
    def validate_non_blank_string(cls, value: str, info: ValidationInfo) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError(f"{_env_name(info.field_name)} cannot be blank")
        return normalized

    @field_validator("telegram_stars_mode")
    @classmethod
    def validate_telegram_stars_mode(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"test", "prod"}:
            raise ValueError("TELEGRAM_STARS_MODE must be test or prod")
        return normalized

    @field_validator("paywall_cooldown_policy")
    @classmethod
    def validate_paywall_cooldown_policy(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized != "none":
            raise ValueError("PAYWALL_COOLDOWN_POLICY must be none for Release 1")
        return normalized

    @field_validator("free_daily_question_limit", "plus_daily_question_limit", "pro_daily_question_limit")
    @classmethod
    def validate_daily_limit(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("Daily question limits must be > 0")
        return value

    @field_validator("plus_price_stars", "pro_price_stars")
    @classmethod
    def validate_optional_stars_price(cls, value: str | None) -> str | None:
        if value is None:
            return value
        if not str(value).isdigit() or int(value) <= 0:
            raise ValueError("Telegram Stars prices must be positive integer strings")
        return str(value)

    @field_validator("plus_duration_days", "pro_duration_days")
    @classmethod
    def validate_optional_duration(cls, value: int | None) -> int | None:
        if value is not None and value <= 0:
            raise ValueError("Subscription durations must be > 0")
        return value

    @field_validator("admin_telegram_user_ids", mode="before")
    @classmethod
    def parse_admin_telegram_user_ids(cls, value: object) -> tuple[int, ...]:
        if value in (None, ""):
            return ()
        if isinstance(value, str):
            raw_values = [item.strip() for item in value.split(",") if item.strip()]
        elif isinstance(value, int):
            raw_values = [value]
        else:
            raw_values = list(value)  # type: ignore[arg-type]

        admin_ids = tuple(int(item) for item in raw_values)
        if any(admin_id <= 0 for admin_id in admin_ids):
            raise ValueError("Admin Telegram user IDs must be positive integers")
        return admin_ids

class Settings(_SettingsValidation):
    @model_validator(mode="after")
    def validate_limit_hierarchy(self) -> "Settings":
        if not (
            self.free_daily_question_limit
            < self.plus_daily_question_limit
            < self.pro_daily_question_limit
        ):
            raise ValueError("Daily question limits must satisfy Free < Plus < Pro")
        return self

    @model_validator(mode="after")
    def validate_webhook_security(self) -> "Settings":
        if not self.bot_webhook_enabled:
            return self

        if not self.telegram_webhook_url:
            raise ValueError("TELEGRAM_WEBHOOK_URL is required when webhook mode is enabled")
        if not self.telegram_webhook_secret or not self.telegram_webhook_secret.get_secret_value():
            raise ValueError("TELEGRAM_WEBHOOK_SECRET is required when webhook mode is enabled")
        if self.telegram_webhook_require_https and not self.telegram_webhook_url.startswith("https://"):
            raise ValueError("TELEGRAM_WEBHOOK_URL must use HTTPS outside development")
        if not self.telegram_webhook_path.startswith("/"):
            raise ValueError("TELEGRAM_WEBHOOK_PATH must start with /")
        return self

    @model_validator(mode="after")
    def validate_runtime_mode(self) -> "Settings":
        if not self.bot_webhook_enabled and not self.bot_polling_enabled:
            raise ValueError("Either BOT_WEBHOOK_ENABLED or BOT_POLLING_ENABLED must be enabled")
        return self

    @model_validator(mode="after")
    def validate_production_security_state(self) -> "Settings":
        if self.app_env == AppEnvironment.development:
            return self
        if self.security_rate_limit_enabled and self.security_state_backend == "in_memory":
            raise ValueError("SECURITY_STATE_BACKEND=in_memory is not allowed outside development")
        if self.security_rate_limit_enabled and not self.redis_url:
            raise ValueError("REDIS_URL is required when production security rate limits are enabled")
        if self.webhook_ingress_backend == WebhookIngressBackend.redis_stream and not self.redis_url:
            raise ValueError("REDIS_URL is required when WEBHOOK_INGRESS_BACKEND=redis_stream")
        if self.training_answer_cache_enabled and not self.redis_url:
            raise ValueError("REDIS_URL is required when TRAINING_ANSWER_CACHE_ENABLED=true")
        if self.training_answer_write_behind_enabled and not self.redis_url:
            raise ValueError("REDIS_URL is required when TRAINING_ANSWER_WRITE_BEHIND_ENABLED=true")
        return self

    @model_validator(mode="after")
    def validate_multi_instance_db_budget(self) -> "Settings":
        if self.db_connection_backend != DbConnectionBackend.pgbouncer_transaction:
            return self
        if self.db_pgbouncer_safe_client_budget < 1:
            raise ValueError("DB_PGBOUNCER_CLIENT_HEADROOM must leave at least one PgBouncer client slot")
        if self.cluster_worker_db_client_budget >= self.db_pgbouncer_safe_client_budget:
            raise ValueError("PgBouncer worker client budget leaves no capacity for app replicas")
        if self.db_pgbouncer_uses_null_pool:
            return self
        if self.cluster_total_pgbouncer_client_budget > self.db_pgbouncer_max_client_conn:
            raise ValueError("PgBouncer client budget exceeds DB_PGBOUNCER_MAX_CLIENT_CONN")
        return self

    @property
    def webhook_mode_enabled(self) -> bool:
        return bool(self.telegram_webhook_url and self.telegram_webhook_secret and self.bot_webhook_enabled)

    @property
    def db_pgbouncer_uses_null_pool(self) -> bool:
        return (
            self.db_connection_backend == DbConnectionBackend.pgbouncer_transaction
            and not self.db_pgbouncer_reuse_app_connections
        )

    @property
    def db_pgbouncer_safe_client_budget(self) -> int:
        return self.db_pgbouncer_max_client_conn - self.db_pgbouncer_client_headroom

    @property
    def effective_worker_db_client_budget_per_replica(self) -> int:
        if self.db_pgbouncer_uses_null_pool:
            return self.db_worker_client_budget_per_replica
        return self.worker_db_pool_size + self.worker_db_max_overflow

    @property
    def cluster_worker_db_client_budget(self) -> int:
        return self.db_worker_replica_count * self.effective_worker_db_client_budget_per_replica

    @property
    def shared_bot_in_flight_limit(self) -> int:
        if self.db_connection_backend != DbConnectionBackend.pgbouncer_transaction:
            return self.bot_global_in_flight_limit
        safe_app_budget = max(1, self.db_pgbouncer_safe_client_budget - self.cluster_worker_db_client_budget)
        return min(self.bot_global_in_flight_limit, safe_app_budget)

    @property
    def cluster_app_db_client_budget(self) -> int:
        if self.db_pgbouncer_uses_null_pool:
            return self.shared_bot_in_flight_limit
        return self.db_app_replica_count * (self.db_pool_size + self.db_max_overflow)

    @property
    def cluster_total_db_client_budget(self) -> int:
        return self.cluster_app_db_client_budget + self.cluster_worker_db_client_budget

    @property
    def cluster_total_pgbouncer_client_budget(self) -> int:
        if self.db_connection_backend != DbConnectionBackend.pgbouncer_transaction:
            return self.cluster_total_db_client_budget
        return self.cluster_total_db_client_budget + self.db_pgbouncer_client_headroom

    @property
    def effective_bot_in_flight_limit(self) -> int:
        if self.db_connection_backend != DbConnectionBackend.pgbouncer_transaction:
            return self.bot_global_in_flight_limit
        if not self.db_pgbouncer_uses_null_pool:
            return self.shared_bot_in_flight_limit
        return max(1, self.shared_bot_in_flight_limit // self.db_app_replica_count)

    @property
    def quiz_bank_edge_api_key_or_legacy(self) -> Optional[str]:
        primary = self.quiz_bank_edge_api_key.get_secret_value() if self.quiz_bank_edge_api_key else None
        legacy = self.quiz_bank_api_key.get_secret_value() if self.quiz_bank_api_key else None
        return primary or legacy

    def require_production_secrets(self) -> None:
        """Fail fast when mandatory production settings are missing."""
        if self.app_env != AppEnvironment.production:
            return

        if not self.bot_webhook_enabled:
            raise ValueError("BOT_WEBHOOK_ENABLED must be true in production")
        if not self.bot_token or not self.bot_token.get_secret_value():
            raise ValueError("BOT_TOKEN is required in production")
        if not self.telegram_webhook_secret or not self.telegram_webhook_secret.get_secret_value():
            raise ValueError("TELEGRAM_WEBHOOK_SECRET is required in production")
        if not self.telegram_webhook_url:
            raise ValueError("TELEGRAM_WEBHOOK_URL is required in production")
        if not self.webhook_mode_enabled:
            raise ValueError("Webhook mode must be fully configured in production")
        if not self.database_url:
            raise ValueError("DATABASE_URL is required in production")
        if self.security_rate_limit_enabled and not self.redis_url:
            raise ValueError("REDIS_URL is required in production")
        if self.webhook_ingress_backend != WebhookIngressBackend.redis_stream:
            raise ValueError("WEBHOOK_INGRESS_BACKEND=redis_stream is required in production")
        if not self.training_answer_cache_enabled:
            raise ValueError("TRAINING_ANSWER_CACHE_ENABLED=true is required in production")
        if not self.training_answer_write_behind_enabled:
            raise ValueError("TRAINING_ANSWER_WRITE_BEHIND_ENABLED=true is required in production")
        if self.telegram_stars_mode != "prod":
            raise ValueError("TELEGRAM_STARS_MODE=prod is required in production")


def _env_name(field_name: str | None) -> str:
    if not field_name:
        return "setting"
    return field_name.upper()


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Load and validate environment configuration."""

    return Settings()  # type: ignore[call-arg]


def clear_settings_cache() -> None:
    """Reset cached settings for tests and controlled runtime reloads."""

    get_settings.cache_clear()
