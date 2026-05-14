from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.quiz_bank import (
    QuizAnswerOption,
    QuizBankErrorResponse,
    QuizCorrectAnswerReference,
    QuizItem,
    QuizQuestionExplanation,
    QuizRequestLimit,
    QuizSourceMetadata,
    QuizQuestionsResponse,
)


def test_quiz_answer_option_schema_validates_text() -> None:
    option = QuizAnswerOption.model_validate({"option_id": "a1", "text": "Antwort", "order": 1})
    assert option.option_id == "a1"


def test_quiz_correct_answer_schema_requires_reference() -> None:
    with pytest.raises(ValidationError):
        QuizCorrectAnswerReference.model_validate({"option_id": "   "})


def test_quiz_item_validates_option_count_and_correct_reference() -> None:
    payload = {
        "item_id": "itm-1",
        "level": "A1",
        "theme": "Artikel",
        "question_text": "Was ist korrekt?",
        "answer_options": [
            {"option_id": "o1", "text": "A"},
            {"option_id": "o2", "text": "B"},
        ],
        "correct_answer": {"option_id": "o1"},
        "explanation": {"text": "Richtig."},
        "metadata": {"progress_theme_key": "artikel"},
    }
    item = QuizItem.model_validate(payload)
    assert item.item_id == "itm-1"
    assert item.correct_answer.option_id == "o1"


def test_quiz_item_rejects_unsupported_level() -> None:
    payload = {
        "item_id": "itm-1",
        "level": "Z9",
        "theme": "Artikel",
        "question_text": "Was ist korrekt?",
        "answer_options": [
            {"option_id": "o1", "text": "A"},
            {"option_id": "o2", "text": "B"},
        ],
        "correct_answer": {"option_id": "o1"},
        "explanation": "Richtig.",
        "metadata": {"progress_theme_key": "artikel"},
    }
    with pytest.raises(ValidationError):
        QuizItem.model_validate(payload)


def test_quiz_item_rejects_duplicate_option_ids() -> None:
    payload = {
        "item_id": "itm-2",
        "level": "B2",
        "theme": "Grammatik",
        "question_text": "Was ist korrekt?",
        "answer_options": [
            {"option_id": "dup", "text": "A"},
            {"option_id": "dup", "text": "B"},
        ],
        "correct_answer": {"option_id": "dup"},
        "explanation": "Richtig.",
        "metadata": {"progress_theme_key": "grammatik"},
    }
    with pytest.raises(ValidationError):
        QuizItem.model_validate(payload)


def test_quiz_item_rejects_incorrect_answer_reference() -> None:
    payload = {
        "item_id": "itm-3",
        "level": "A2",
        "theme": "Artikel",
        "question_text": "Was ist korrekt?",
        "answer_options": [
            {"option_id": "o1", "text": "A"},
            {"option_id": "o2", "text": "B"},
        ],
        "correct_answer": {"option_id": "x"},
        "explanation": "Richtig.",
        "metadata": {"progress_theme_key": "artikel"},
    }
    with pytest.raises(ValidationError):
        QuizItem.model_validate(payload)


def test_quiz_question_batch_schema_success() -> None:
    payload = {
        "items": [
            {
                "item_id": "itm-1",
                "level": "A1",
                "theme": "Artikel",
                "question_text": "Was ist korrekt?",
                "answer_options": [
                    {"option_id": "o1", "text": "A"},
                    {"option_id": "o2", "text": "B"},
                ],
                "correct_answer": {"option_id": "o1"},
                "explanation": {"text": "Richtig."},
                "metadata": {"progress_theme_key": "artikel"},
                "source_metadata": {"source": "quiz_bank_api"},
            }
        ],
        "requested_count": 1,
        "returned_count": 1,
        "has_more": False,
    }
    response = QuizQuestionsResponse.model_validate(payload)
    assert len(response.items) == 1
    assert response.requested_count == 1


def test_quiz_question_batch_schema_rejects_wrong_count() -> None:
    payload = {
        "items": [],
        "requested_count": 1,
        "returned_count": -1,
    }
    with pytest.raises(ValidationError):
        QuizQuestionsResponse.model_validate(payload)


def test_api_error_schema_parses() -> None:
    data = QuizBankErrorResponse.model_validate(
        {
            "error_code": "not_found",
            "error_message": "Item not found",
            "request_id": "rq-1",
            "status_code": 404,
            "details": {"item_id": "foo"},
        },
    )
    assert data.error_code == "not_found"


def test_quiz_request_limit_schema_enforces_bounds() -> None:
    with pytest.raises(ValidationError):
        QuizRequestLimit.model_validate({"limit": 0})


def test_quiz_optional_metadata_models_validate() -> None:
    source = QuizSourceMetadata.model_validate(
        {"source": "quiz_bank_api", "request_id": "rq-1", "content_version": "v1"},
    )
    explanation = QuizQuestionExplanation.model_validate({"text": "Роз’яснення."})
    option = QuizAnswerOption.model_validate({"option_id": "o1", "text": "A", "order": 1})

    assert source.source == "quiz_bank_api"
    assert explanation.text == "Роз’яснення."
    assert option.order == 1
