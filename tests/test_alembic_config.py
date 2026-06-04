from __future__ import annotations

from pathlib import Path

from alembic.script import ScriptDirectory
from alembic.config import Config

from app.db.base import Base
from app.db import models  # noqa: F401


def test_alembic_env_imports_metadata() -> None:
    assert len(Base.metadata.tables) >= 7
    env_text = Path("alembic/env.py").read_text(encoding="utf-8")
    assert "from app.db import models" in env_text
    assert "target_metadata = Base.metadata" in env_text


def test_alembic_directory_exists() -> None:
    script = ScriptDirectory.from_config(Config("alembic.ini"))
    dirs = [revision.path for revision in script.walk_revisions()]
    assert any("202605140001_initial_schema" in str(path) for path in dirs)
    assert any("202605140002_extend_milestone2_schema" in str(path) for path in dirs)
