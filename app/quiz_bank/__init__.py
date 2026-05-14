"""Quiz Bank API integration boundary."""

from .client import QuizBankAsyncClient
from .errors import (
    QuizBankAuthError,
    QuizBankConfigError,
    QuizBankRateLimitError,
    QuizBankUnavailableError,
    QuizBankValidationError,
)
from .schemas import (
    QuizAvailabilityResponse,
    QuizAnswerOption,
    QuizBankErrorResponse,
    QuizBankRequestContext,
    QuizCorrectAnswerReference,
    QuizHealthResponse,
    QuizItem,
    QuizLevel,
    QuizLevelsResponse,
    QuizMetadataResponse,
    QuizQuestionExplanation,
    QuizQuestionLookupResponse,
    QuizRequestLimit,
    QuizSourceMetadata,
    QuizTheme,
    QuizThemesResponse,
    QuizQuestionsResponse,
)
from .service import QuizBankService

__all__ = [
    "QuizBankAsyncClient",
    "QuizBankAuthError",
    "QuizBankConfigError",
    "QuizBankRateLimitError",
    "QuizBankUnavailableError",
    "QuizBankValidationError",
    "QuizAvailabilityResponse",
    "QuizAnswerOption",
    "QuizBankErrorResponse",
    "QuizBankRequestContext",
    "QuizCorrectAnswerReference",
    "QuizHealthResponse",
    "QuizItem",
    "QuizLevel",
    "QuizLevelsResponse",
    "QuizMetadataResponse",
    "QuizQuestionExplanation",
    "QuizQuestionLookupResponse",
    "QuizRequestLimit",
    "QuizSourceMetadata",
    "QuizTheme",
    "QuizThemesResponse",
    "QuizQuestionsResponse",
    "QuizBankService",
]
