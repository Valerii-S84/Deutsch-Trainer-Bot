from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


def canonical_json(value: Any) -> str:
    """Return deterministic JSON for checksum input."""

    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def checksum_mapping(value: dict[str, Any]) -> str:
    return sha256_text(canonical_json(value))


def selection_key_from_checksum(checksum: str) -> int:
    """Map a SHA-256 checksum into signed BIGINT-safe positive space."""

    return int(checksum[:16], 16) & 0x7FFF_FFFF_FFFF_FFFF


def checksum_files(paths: list[Path]) -> str:
    digest = hashlib.sha256()
    for path in sorted(paths):
        digest.update(path.name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()
