"""Pydantic schemas for Quiz Bank API responses."""

from __future__ import annotations

from typing import Any, Final

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator, model_validator

SUPPORTED_LEVELS: Final[set[str]] = {"A1", "A2", "B1", "B2", "C1"}


class QuizBankRequestContext(BaseModel):
    """Optional quiz user/session context passed to Quiz Bank."""

    session_type: str | None = None
    seen_item_ids: list[str] | None = None
    mistake_item_ids: list[str] | None = None
    weak_theme_keys: list[str] | None = None
    target_level: str | None = None
    item_ids: list[str] | None = None
    exclude_seen: bool | None = None
    exclude_item_ids: list[str] | None = None

    model_config = ConfigDict(extra="forbid")


class QuizRequestLimit(BaseModel):
    """Limit contract for batch questions request."""

    limit: int = Field(ge=1, le=50)


class QuizAnswerOption(BaseModel):
    option_id: str
    text: str
    order: int | None = None

    model_config = ConfigDict(extra="forbid")

    @field_validator("option_id")
    @classmethod
    def non_empty_option_id(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("option_id must be non-empty")
        return value

    @field_validator("text")
    @classmethod
    def non_empty_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("text must be non-empty")
        return value


class QuizCorrectAnswerReference(BaseModel):
    """Reference to a valid answer option id."""

    option_id: str

    @field_validator("option_id")
    @classmethod
    def non_empty_option_id(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("correct answer option_id must be non-empty")
        return value


class QuizQuestionExplanation(BaseModel):
    text: str

    @field_validator("text")
    @classmethod
    def non_empty_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("explanation text must be non-empty")
        return value


class QuizSourceMetadata(BaseModel):
    """Quiz source metadata for progress and diagnostics."""

    source: str
    source_metadata: dict[str, Any] | None = None
    request_id: str | None = None
    content_version: str | None = None

    @field_validator("source")
    @classmethod
    def non_empty_source(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("source must be non-empty")
        return value


class QuizItem(BaseModel):
    """Validated quiz question item."""

    item_id: str
    level: str
    theme: str
    question_text: str
    answer_options: list[QuizAnswerOption]
    correct_answer: QuizCorrectAnswerReference
    explanation: QuizQuestionExplanation | str
    metadata: dict[str, Any]
    theme_key: str | None = None
    content_version: str | None = None
    source_metadata: QuizSourceMetadata | None = None

    model_config = ConfigDict(extra="allow")

    @field_validator("item_id", "level", "theme", "question_text")
    @classmethod
    def strip_strings(cls, value: str, info: ValidationInfo) -> str:
        value = value.strip()
        if not value:
            raise ValueError(f"{info.field_name} cannot be empty")
        return value

    @field_validator("level")
    @classmethod
    def supported_level(cls, value: str, _: ValidationInfo) -> str:
        if value not in SUPPORTED_LEVELS:
            raise ValueError(f"unsupported level: {value}")
        return value

    @field_validator("answer_options")
    @classmethod
    def validate_options_count(cls, value: list[QuizAnswerOption]) -> list[QuizAnswerOption]:
        if len(value) < 2:
            raise ValueError("at least two answer options are required")
        option_ids = {opt.option_id for opt in value}
        if len(option_ids) != len(value):
            raise ValueError("answer option ids must be unique")
        return value

    @model_validator(mode="after")
    def validate_correct_answer(self) -> "QuizItem":
        option_ids = {option.option_id for option in self.answer_options}
        if self.correct_answer.option_id not in option_ids:
            raise ValueError("correct_answer must reference an existing option_id")
        return self


class QuizQuestionsResponse(BaseModel):
    """Contract for /questions endpoint."""

    items: list[QuizItem]
    requested_count: int
    returned_count: int
    has_more: bool = False

    @field_validator("requested_count")
    @classmethod
    def positive_requested_count(cls, value: int) -> int:
        if value < 0:
            raise ValueError("requested_count must be >= 0")
        return value

    @field_validator("returned_count")
    @classmethod
    def non_negative_returned_count(cls, value: int) -> int:
        if value < 0:
            raise ValueError("returned_count must be >= 0")
        return value


class QuizBankErrorResponse(BaseModel):
    """Error response from protected Quiz Bank API."""

    error_code: str
    error_message: str
    request_id: str | None = None
    status_code: int | None = None
    details: dict[str, Any] | None = None

    @field_validator("error_code", "error_message")
    @classmethod
    def non_empty_error_fields(cls, value: str, info: ValidationInfo) -> str:
        value = value.strip()
        if not value:
            raise ValueError(f"{info.field_name} must be non-empty")
        return value
