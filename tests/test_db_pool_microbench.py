from __future__ import annotations

from types import SimpleNamespace

import pytest

from scripts import db_pool_microbench as script


def test_current_max_rss_mb_returns_zero_when_resource_module_is_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(script, "_resource", None)

    assert script.current_max_rss_mb() == 0.0


def test_current_max_rss_mb_uses_resource_module_when_available(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_resource = SimpleNamespace(
        RUSAGE_SELF=1,
        getrusage=lambda _target: SimpleNamespace(ru_maxrss=3072),
    )
    monkeypatch.setattr(script, "_resource", fake_resource)

    assert script.current_max_rss_mb() == 3.0
