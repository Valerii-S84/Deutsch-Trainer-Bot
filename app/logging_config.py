from __future__ import annotations

import logging
import re
from typing import Final

SENSITIVE_KEYS: Final = ("token", "secret", "key", "password", "authorization", "api-key")


def _redact(text: str) -> str:
    redacted = text
    for key in SENSITIVE_KEYS:
        redacted = re.sub(
            rf"(?i){re.escape(key)}[=:][^\\s\"]+",
            f"{key}=***",
            redacted,
        )
    return redacted


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
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    root.addFilter(SecretRedactionFilter())

