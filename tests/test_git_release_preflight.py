from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "git_release_preflight.sh"


def test_git_release_preflight_passes_for_clean_feature_branch(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    _run_git(repo, "remote", "add", "origin", "https://github.com/example/deutsch-trainer-bot.git")

    completed = _run_preflight(repo, expected_branch="chore/test-release")

    assert completed.returncode == 0
    assert "git release preflight finished" in completed.stdout


def test_git_release_preflight_rejects_missing_remote(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)

    completed = _run_preflight(repo, expected_branch="chore/test-release")

    assert completed.returncode == 1
    assert "remote origin is not configured" in completed.stderr


def test_git_release_preflight_rejects_rejected_repository(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    _run_git(repo, "remote", "add", "origin", "https://github.com/yuzhnyi/deutsch-trainer-bot.git")

    completed = _run_preflight(repo, expected_branch="chore/test-release")

    assert completed.returncode == 1
    assert "rejected repository" in completed.stderr


def _init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _run_git(repo, "init", "-b", "main")
    _run_git(repo, "config", "user.email", "test@example.invalid")
    _run_git(repo, "config", "user.name", "Test User")
    (repo / "README.md").write_text("test\n", encoding="utf-8")
    _run_git(repo, "add", "README.md")
    _run_git(repo, "commit", "-m", "test: initial")
    _run_git(repo, "checkout", "-b", "chore/test-release")
    return repo


def _run_git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        ("git", *args),
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    return completed


def _run_preflight(repo: Path, *, expected_branch: str) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "EXPECTED_BRANCH": expected_branch}
    return subprocess.run(
        (BASH_PATH, str(SCRIPT_PATH)),
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def _find_usable_bash() -> str | None:
    for candidate in _bash_candidates():
        if _is_usable_bash(candidate):
            return candidate
    return None


def _bash_candidates() -> tuple[str, ...]:
    candidates: list[str] = []
    env_bash = os.environ.get("BASH")
    if env_bash:
        candidates.append(env_bash)
    if os.name == "nt":
        candidates.extend(
            (
                r"C:\Program Files\Git\bin\bash.exe",
                r"C:\Program Files\Git\usr\bin\bash.exe",
            ),
        )
    path_bash = shutil.which("bash")
    if path_bash:
        candidates.append(path_bash)
    return tuple(dict.fromkeys(candidates))


def _is_usable_bash(candidate: str) -> bool:
    try:
        completed = subprocess.run(
            (candidate, "-lc", ":"),
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return completed.returncode == 0


BASH_PATH = _find_usable_bash()
pytestmark = [
    pytest.mark.skipif(shutil.which("git") is None, reason="git is required"),
    pytest.mark.skipif(BASH_PATH is None, reason="executable bash is required"),
]
