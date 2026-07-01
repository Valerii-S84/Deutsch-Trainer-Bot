"""Pydantic schemas for Quiz Bank API responses."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Final

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator, model_validator

SUPPORTED_LEVELS: Final[set[str]] = {"A1", "A2", "B1", "B2", "C1", "C2"}


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


class QuizHealthResponse(BaseModel):
    """Contract for /health endpoint."""

    status: str
    service: str
    checked_at: datetime
    version: str | None = None
    content_version: str | None = None

    model_config = ConfigDict(extra="allow")

    @field_validator("status")
    @classmethod
    def known_status(cls, value: str) -> str:
        value = value.strip().lower()
        if value not in {"ok", "degraded", "unavailable"}:
            raise ValueError("unsupported health status")
        return value

    @field_validator("service")
    @classmethod
    def non_empty_service(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("service must be non-empty")
        return value


class QuizLevel(BaseModel):
    """Level catalog entry."""

    code: str
    display_name: str
    is_active: bool

    model_config = ConfigDict(extra="allow")

    @field_validator("code")
    @classmethod
    def normalize_code(cls, value: str) -> str:
        value = value.strip().upper()
        if not value:
            raise ValueError("level code must be non-empty")
        return value

    @field_validator("display_name")
    @classmethod
    def non_empty_display_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("display_name must be non-empty")
        return value


class QuizLevelsResponse(BaseModel):
    """Contract for /levels endpoint."""

    levels: list[QuizLevel]
    content_version: str | None = None

    model_config = ConfigDict(extra="allow")


class QuizTheme(BaseModel):
    """Theme catalog entry for a level."""

    theme: str
    theme_key: str
    is_active: bool
    available_items_count: int | None = Field(default=None, ge=0)
    metadata: dict[str, Any] | None = None

    model_config = ConfigDict(extra="allow")

    @field_validator("theme", "theme_key")
    @classmethod
    def non_empty_theme_fields(cls, value: str, info: ValidationInfo) -> str:
        value = value.strip()
        if not value:
            raise ValueError(f"{info.field_name} must be non-empty")
        return value


class QuizThemesResponse(BaseModel):
    """Contract for /levels/{level}/themes endpoint."""

    level: str
    themes: list[QuizTheme]
    content_version: str | None = None

    model_config = ConfigDict(extra="allow")

    @field_validator("level")
    @classmethod
    def supported_level(cls, value: str) -> str:
        value = value.strip().upper()
        if value not in SUPPORTED_LEVELS:
            raise ValueError(f"unsupported level: {value}")
        return value


class QuizAvailabilityResponse(BaseModel):
    """Contract for /availability endpoint."""

    level: str
    theme: str
    theme_key: str
    available_items_count: int = Field(ge=0)
    generated_at: datetime
    active_items_count: int | None = Field(default=None, ge=0)
    inactive_items_count: int | None = Field(default=None, ge=0)
    content_version: str | None = None

    model_config = ConfigDict(extra="allow")

    @field_validator("level")
    @classmethod
    def supported_level(cls, value: str) -> str:
        value = value.strip().upper()
        if value not in SUPPORTED_LEVELS:
            raise ValueError(f"unsupported level: {value}")
        return value

    @field_validator("theme", "theme_key")
    @classmethod
    def non_empty_availability_fields(cls, value: str, info: ValidationInfo) -> str:
        value = value.strip()
        if not value:
            raise ValueError(f"{info.field_name} must be non-empty")
        return value


class QuizMetadataResponse(BaseModel):
    """Contract for /metadata endpoint."""

    levels: list[str]
    themes: list[str]
    metadata_version: str
    generated_at: datetime
    question_types: list[str] | None = None
    difficulty_scale: dict[str, Any] | None = None
    skill_areas: list[str] | None = None

    model_config = ConfigDict(extra="allow")

    @field_validator("metadata_version")
    @classmethod
    def non_empty_metadata_version(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("metadata_version must be non-empty")
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

    @field_validator("correct_answer", mode="before")
    @classmethod
    def normalize_correct_answer(cls, value: object) -> object:
        if isinstance(value, str):
            return {"option_id": value}
        return value

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

    @field_validator("explanation")
    @classmethod
    def validate_explanation(cls, value: QuizQuestionExplanation | str) -> QuizQuestionExplanation | str:
        if isinstance(value, str) and not value.strip():
            raise ValueError("explanation must be non-empty")
        return value

    @field_validator("metadata")
    @classmethod
    def validate_progress_metadata(cls, value: dict[str, Any]) -> dict[str, Any]:
        if not value:
            raise ValueError("metadata must be non-empty")
        progress_theme_key = value.get("progress_theme_key")
        if not isinstance(progress_theme_key, str) or not progress_theme_key.strip():
            raise ValueError("metadata.progress_theme_key is required")
        return value

    @model_validator(mode="after")
    def validate_correct_answer(self) -> "QuizItem":
        option_ids = {option.option_id for option in self.answer_options}
        if self.correct_answer.option_id not in option_ids:
            raise ValueError("correct_answer must reference an existing option_id")
        return self


class QuizQuestionLookupResponse(QuizItem):
    """Contract for /questions/{item_id} endpoint."""

    is_active: bool
    replaced_by_item_id: str | None = None
    deactivated_reason: str | None = None


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

    @model_validator(mode="after")
    def validate_returned_count(self) -> "QuizQuestionsResponse":
        if self.returned_count != len(self.items):
            raise ValueError("returned_count must match items length")
        if self.returned_count > self.requested_count:
            raise ValueError("returned_count must not exceed requested_count")
        return self


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
