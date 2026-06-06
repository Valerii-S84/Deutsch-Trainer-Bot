from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import SecretStr

from app.config import Settings
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


def test_parse_smoke_item_ids_normalizes_level_mapping() -> None:
    module = load_smoke_module()

    assert module.parse_smoke_item_ids(" a1=item-1, B1 = item-2 ") == {"A1": "item-1", "B1": "item-2"}


def test_parse_smoke_item_ids_rejects_unscoped_values() -> None:
    module = load_smoke_module()

    with pytest.raises(QuizBankError, match="LEVEL=item_id"):
        module.parse_smoke_item_ids("item-1")


@pytest.mark.asyncio
async def test_build_smoke_client_honors_settings_timeout_and_retries() -> None:
    module = load_smoke_module()
    settings = Settings(
        quiz_bank_api_base_url="https://quiz-bank.test",
        quiz_bank_edge_api_key=SecretStr("edge-key"),
        quiz_bank_consumer_api_key=SecretStr("consumer-key"),
        quiz_bank_consumer_id="consumer-1",
        quiz_bank_timeout_seconds=9,
        quiz_bank_max_retries=4,
    )

    client = module.build_smoke_client(settings)
    try:
        assert client._timeout_seconds == 9
        assert client._max_retries == 4
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_run_smoke_uses_display_theme_and_read_only_resolution() -> None:
    module = load_smoke_module()
    service = FakeSmokeService()

    result = await module.run_smoke(("A1",), service=service)

    assert result == 0
    assert ("resolve_theme_ids", "Artikel") in service.calls
    assert ("availability", "A1", "Artikel") in service.calls
    assert not any(call[0] == "request_quiz" for call in service.calls)


@pytest.mark.asyncio
async def test_run_smoke_uses_optional_read_only_question_lookup() -> None:
    module = load_smoke_module()
    service = FakeSmokeService()

    await module.run_smoke(("A1",), smoke_item_ids_by_level={"A1": "itm-1"}, service=service)

    assert ("question", "itm-1") in service.calls
    assert not any(call[0] == "request_quiz" for call in service.calls)


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


class FakeSmokeService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []

    async def get_health(self):
        self.calls.append(("health",))
        return SimpleNamespace(status="ok")

    async def get_levels(self):
        self.calls.append(("levels",))
        return SimpleNamespace(levels=[SimpleNamespace(code="A1", is_active=True)])

    async def get_themes(self, *, level: str):
        self.calls.append(("themes", level))
        return SimpleNamespace(themes=[SimpleNamespace(theme="Artikel", theme_key="T01")])

    async def resolve_theme_ids(self, *, theme: str):
        self.calls.append(("resolve_theme_ids", theme))
        return ["T01"]

    async def get_availability(self, *, level: str, theme: str):
        self.calls.append(("availability", level, theme))
        return SimpleNamespace(available_items_count=1)

    async def get_question(self, *, item_id: str):
        self.calls.append(("question", item_id))
        return QuizItem.model_validate(
            {
                "item_id": item_id,
                "level": "A1",
                "theme": "Artikel",
                "question_text": "Was ist korrekt?",
                "answer_options": [
                    {"option_id": "a", "text": "der"},
                    {"option_id": "b", "text": "die"},
                ],
                "correct_answer": "a",
                "explanation": "Richtig.",
                "metadata": {"progress_theme_key": "artikel"},
            },
        )

    async def request_quiz(self, **_: object):
        self.calls.append(("request_quiz",))
        raise AssertionError("live smoke must not request delivery")
