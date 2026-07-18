from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ResolvedUserId:
    """Internal user identity that has already been resolved from Telegram."""

    value: int
