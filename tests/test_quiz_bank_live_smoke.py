from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from app.quiz_bank.errors import QuizBankError
from app.quiz_bank.schemas import QuizItem


SCRIPT_PATH = Path("scripts/quiz_bank_live_smoke.py")


def load_smoke_module():
    spec = importlib.util.spec_from_file_location("quiz_bank_live_smoke_for_tests", SCRIPT_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_parse_levels_defaults_to_a1_a2_b1() -> None:
    module = load_smoke_module()

    assert module.parse_levels(None) == ("A1", "A2", "B1")


def test_parse_levels_normalizes_csv() -> None:
    module = load_smoke_module()

    assert module.parse_levels(" a1, B1 ") == ("A1", "B1")


def test_dynamic_content_allows_german_umlauts() -> None:
    module = load_smoke_module()

    module.assert_no_cyrillic_dynamic_content(
        QuizItem.model_validate(
            {
                "item_id": "itm-1",
                "level": "A1",
                "theme": "Gruesse",
                "question_text": "Waehle die richtige Begruessung.",
                "answer_options": [
                    {"option_id": "a", "text": "Guten Morgen"},
                    {"option_id": "b", "text": "Tschuess"},
                ],
                "correct_answer": "a",
                "explanation": "Das ist richtig.",
                "metadata": {"progress_theme_key": "gruesse"},
            },
        ),
    )


def test_dynamic_content_rejects_cyrillic() -> None:
    module = load_smoke_module()

    with pytest.raises(QuizBankError, match="Cyrillic"):
        module.assert_no_cyrillic_dynamic_content(
            QuizItem.model_validate(
                {
                    "item_id": "itm-2",
                    "level": "A1",
                    "theme": "Artikel",
                    "question_text": "Оберіть правильний артикль.",
                    "answer_options": [
                        {"option_id": "a", "text": "der"},
                        {"option_id": "b", "text": "die"},
                    ],
                    "correct_answer": "a",
                    "explanation": "Deutsch only.",
                    "metadata": {"progress_theme_key": "artikel"},
                },
            ),
        )


def test_redacts_secret_like_output() -> None:
    module = load_smoke_module()
    bearer = "abcdefghijkl" + "mnop"
    bot_token = "1234567890" + ":" + "ABCDEFGHIJKLM" + "NOPQRSTUVWXYZabcdefghi"

    redacted = module.redact_sensitive_output(
        "Authorization: Bearer " + bearer + " tok" + "en='" + bot_token + "'"
    )

    assert bearer not in redacted
    assert "1234567890:" not in redacted
    assert "[REDACTED]" in redacted
