"""Custom exceptions for Quiz Bank integration."""

from __future__ import annotations

from typing import Optional


class QuizBankError(Exception):
    """Base class for all Quiz Bank integration errors."""

    def __init__(
        self,
        message: str,
        *,
        request_id: Optional[str] = None,
        status_code: Optional[int] = None,
        endpoint: Optional[str] = None,
    ) -> None:
        self.request_id = request_id
        self.status_code = status_code
        self.endpoint = endpoint
        self.message = message
        context = []
        if endpoint:
            context.append(f"endpoint={endpoint}")
        if status_code:
            context.append(f"status_code={status_code}")
        if request_id:
            context.append(f"request_id={request_id}")
        suffix = ", ".join(context)
        if suffix:
            super().__init__(f"{message} ({suffix})")
        else:
            super().__init__(message)


class QuizBankConfigError(QuizBankError):
    """Configuration problems (missing API endpoint or secret keys)."""


class QuizBankAuthError(QuizBankError):
    """Auth/authorization failures from Quiz Bank (401/403)."""


class QuizBankRateLimitError(QuizBankError):
    """Rate limiting responses from Quiz Bank (429)."""


class QuizBankUnavailableError(QuizBankError):
    """Transport and server errors."""


class QuizBankValidationError(QuizBankError):
    """Invalid payload or schema from Quiz Bank."""

