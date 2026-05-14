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
    QuizAnswerOption,
    QuizBankErrorResponse,
    QuizBankRequestContext,
    QuizCorrectAnswerReference,
    QuizItem,
    QuizQuestionExplanation,
    QuizRequestLimit,
    QuizSourceMetadata,
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
    "QuizAnswerOption",
    "QuizBankErrorResponse",
    "QuizBankRequestContext",
    "QuizCorrectAnswerReference",
    "QuizItem",
    "QuizQuestionExplanation",
    "QuizRequestLimit",
    "QuizSourceMetadata",
    "QuizQuestionsResponse",
    "QuizBankService",
]
