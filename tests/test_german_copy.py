from __future__ import annotations

import ast
import re
from pathlib import Path

import app.bot.texts as bot_texts


TEXTS_PATH = Path("app/bot/texts.py")
KEYBOARDS_DIR = Path("app/bot/keyboards")
CYRILLIC_RE = re.compile(r"[\u0400-\u04FF]")
FORBIDDEN_ENGLISH_RE = re.compile(
    r"\b(?:please|try again|payment|subscription|progress|mistakes|main menu|continue|cancel|retry|unknown|invalid|failed|success|error)\b",
    re.IGNORECASE,
)
USER_COPY_SUFFIXES = ("_TEXT", "_PROMPT", "_HEADER", "_BUTTON_TEXT")


def test_bot_text_constants_are_german_only_copy() -> None:
    findings = [
        f"{name}: {text}"
        for name, text in iter_bot_text_constants()
        if CYRILLIC_RE.search(text) or FORBIDDEN_ENGLISH_RE.search(text)
    ]

    assert findings == []


def test_keyboard_literal_button_text_is_german_only_copy() -> None:
    findings = [
        f"{path}:{line}: {text}"
        for path, line, text in iter_keyboard_text_literals()
        if CYRILLIC_RE.search(text) or FORBIDDEN_ENGLISH_RE.search(text)
    ]

    assert findings == []


def iter_bot_text_constants() -> tuple[tuple[str, str], ...]:
    constants: list[tuple[str, str]] = []
    for name in dir(bot_texts):
        if not is_user_copy_constant(name):
            continue
        value = getattr(bot_texts, name)
        if isinstance(value, str):
            constants.append((name, value))
    return tuple(constants)


def is_user_copy_constant(name: str) -> bool:
    return name.startswith("MENU_BUTTON_") or name.endswith(USER_COPY_SUFFIXES)


def iter_keyboard_text_literals() -> tuple[tuple[Path, int, str], ...]:
    literals: list[tuple[Path, int, str]] = []
    for path in sorted(KEYBOARDS_DIR.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            literals.extend(extract_text_keyword_literals(path, node))
    return tuple(literals)


def extract_text_keyword_literals(path: Path, node: ast.AST) -> tuple[tuple[Path, int, str], ...]:
    if not isinstance(node, ast.Call):
        return ()
    literals: list[tuple[Path, int, str]] = []
    for keyword in node.keywords:
        if keyword.arg != "text":
            continue
        if isinstance(keyword.value, ast.Constant) and isinstance(keyword.value.value, str):
            literals.append((path, keyword.value.lineno, keyword.value.value))
    return tuple(literals)

