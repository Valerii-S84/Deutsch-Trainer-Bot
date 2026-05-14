from __future__ import annotations


_MARKDOWN_CHARS = "\\`*_[]()"


def escape_markdown_text(value: object) -> str:
    """Escape untrusted text before inserting it into Telegram Markdown."""
    text = "" if value is None else str(value)
    for char in _MARKDOWN_CHARS:
        text = text.replace(char, f"\\{char}")
    return text
