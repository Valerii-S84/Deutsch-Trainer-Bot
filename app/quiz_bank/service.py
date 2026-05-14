"""Service layer for Quiz Bank integration."""

from __future__ import annotations

from app.config import Settings, get_settings
from pydantic import ValidationError

from .client import QuizBankAsyncClient
from .errors import QuizBankValidationError
from .schemas import (
    QuizBankRequestContext,
    QuizQuestionsResponse,
)


class QuizBankService:
    """Business-safe Quiz Bank service used by bot flow."""

    def __init__(self, client: QuizBankAsyncClient | None = None, settings: Settings | None = None) -> None:
        if settings is None:
            settings = get_settings()
        self._client = client or QuizBankAsyncClient(
            base_url=settings.quiz_bank_api_base_url,
            edge_api_key=settings.quiz_bank_edge_api_key_or_legacy,
            consumer_api_key=settings.quiz_bank_consumer_api_key.get_secret_value()
            if settings.quiz_bank_consumer_api_key
            else None,
            consumer_id=settings.quiz_bank_consumer_id,
            timeout_seconds=settings.quiz_bank_timeout_seconds,
            max_retries=settings.quiz_bank_max_retries,
            settings=settings,
        )

    async def request_quiz(
        self,
        *,
        level: str,
        theme: str | None,
        limit: int | None = None,
        user_context: QuizBankRequestContext | None = None,
    ) -> QuizQuestionsResponse:
        """
        Request quiz items for a given level/theme contract.

        This method validates response payload before returning it to callers.
        """
        if limit is None:
            limit = 1

        if limit <= 0:
            raise QuizBankValidationError("limit must be greater than 0")

        level_value = level.strip()
        if not level_value:
            raise QuizBankValidationError("level is required")

        if theme is not None:
            theme_value = theme.strip()
            if not theme_value:
                raise QuizBankValidationError("theme cannot be empty if provided")
        else:
            theme_value = None

        context = user_context.model_dump(exclude_none=True) if user_context else None
        payload = await self._client.fetch_questions(
            level=level_value,
            theme=theme_value,
            limit=limit,
            user_context=context,
        )
        try:
            return QuizQuestionsResponse.model_validate(payload)
        except ValidationError as exc:
            raise QuizBankValidationError("Quiz Bank questions response is invalid") from exc
