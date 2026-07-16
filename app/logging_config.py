from __future__ import annotations

import logging
import re
from typing import Final

SENSITIVE_VALUE_PATTERN: Final = re.compile(
    r"(?i)\b(token|secret|api[_-]?key|password|credential|database_url|dsn|private_key)\b"
    r"\s*[:=]\s*(\"[^\"]*\"|'[^']*'|[^\s,]+)",
)
AUTHORIZATION_PATTERN: Final = re.compile(r"(?i)\b(authorization)\b\s*[:=]\s*[^,]+")
BEARER_PATTERN: Final = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+")
DATABASE_URL_PATTERN: Final = re.compile(r"(?i)\b(?:postgresql|postgres|redis)(?:\+asyncpg)?://[^\s,]+")
TELEGRAM_TOKEN_PATTERN: Final = re.compile(r"\b\d{8,12}:[A-Za-z0-9_-]{35,}\b")
PRIVATE_KEY_PATTERN: Final = re.compile(
    r"-----BEGIN (?:RSA |EC |OPENSSH |)PRIVATE KEY-----.*?"
    r"-----END (?:RSA |EC |OPENSSH |)PRIVATE KEY-----",
    re.DOTALL,
)


def _redact(text: str) -> str:
    redacted = PRIVATE_KEY_PATTERN.sub("private_key=***", text)
    redacted = AUTHORIZATION_PATTERN.sub(lambda match: f"{match.group(1)}=***", redacted)
    redacted = BEARER_PATTERN.sub("Bearer ***", redacted)
    redacted = DATABASE_URL_PATTERN.sub("database_url=***", redacted)
    redacted = TELEGRAM_TOKEN_PATTERN.sub("telegram_bot_token=***", redacted)
    return SENSITIVE_VALUE_PATTERN.sub(lambda match: f"{match.group(1)}=***", redacted)


def log_exception_summary(
    logger: logging.Logger,
    log_event: str,
    exc: Exception,
    *,
    level: int = logging.ERROR,
    **context: object,
) -> None:
    context_parts = [
        f"{key}={_single_line(value)}"
        for key, value in context.items()
        if value is not None
    ]
    if context_parts:
        logger.log(level, "%s %s error_type=%s", log_event, " ".join(context_parts), exc.__class__.__name__)
        return
    logger.log(level, "%s error_type=%s", log_event, exc.__class__.__name__)


def _single_line(value: object) -> str:
    return str(value).replace("\r", " ").replace("\n", " ")


class SecretRedactionFilter(logging.Filter):
    """Filter that redacts obvious sensitive fields from log messages."""

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        record.msg = _redact(message)
        record.args = ()
        return True


def configure_logging(level: str = "INFO") -> None:
    """Configure structured-lean logging with basic secret redaction."""
    root = logging.getLogger()
    root.handlers = []
    redaction_filter = SecretRedactionFilter()
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    for handler in root.handlers:
        handler.addFilter(redaction_filter)
