from __future__ import annotations

import pytest
from types import SimpleNamespace
from unittest.mock import Mock

from app.repositories.answers import AnswerRepository


@pytest.mark.asyncio
async def test_answer_create_mirrors_external_quiz_id_to_item_id() -> None:
    db = SimpleNamespace(add=Mock())
    answer = await AnswerRepository().create(
        db,
        session_id=1,
        user_id=1,
        external_quiz_id="quiz-bank-item-1",
        selected_answer="a",
        correct_answer="a",
        is_correct=True,
    )

    assert answer.item_id == "quiz-bank-item-1"
    db.add.assert_called_once_with(answer)
