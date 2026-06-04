from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


SCRIPT_PATH = Path("scripts/static_policy_check.py")


def load_static_policy_module():
    spec = importlib.util.spec_from_file_location("static_policy_check_for_tests", SCRIPT_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_static_policy_check_validates_shell_scripts() -> None:
    module = load_static_policy_module()

    module.validate_shell_scripts()


def test_isolated_runtime_smoke_passes_stdin_to_container_python() -> None:
    script = Path("scripts/isolated_runtime_smoke.sh").read_text(encoding="utf-8")

    assert 'docker exec "$BOT_CONTAINER" python - <<' not in script
    assert script.count('docker exec -i "$BOT_CONTAINER" python - <<') == 4
