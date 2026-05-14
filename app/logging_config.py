from __future__ import annotations

import logging
import re
from typing import Final

SENSITIVE_VALUE_PATTERN: Final = re.compile(
    r"(?i)\b(token|secret|api-key|password|key)\b\s*[:=]\s*(\"[^\"]*\"|'[^']*'|[^\s,]+)",
)
AUTHORIZATION_PATTERN: Final = re.compile(r"(?i)\b(authorization)\b\s*[:=]\s*[^,]+")


def _redact(text: str) -> str:
    redacted = AUTHORIZATION_PATTERN.sub(lambda match: f"{match.group(1)}=***", text)
    return SENSITIVE_VALUE_PATTERN.sub(lambda match: f"{match.group(1)}=***", redacted)


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
