from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil
import subprocess
from uuid import uuid4


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a local Caddy ingress process for load tests.")
    parser.add_argument("--config", required=True, help="Rendered Caddyfile path.")
    parser.add_argument("--image", default="caddy:2.8", help="Local Docker image to extract Caddy from.")
    args = parser.parse_args()

    config_path = Path(args.config).resolve()
    caddy_binary = _resolve_caddy_binary(config_path=config_path, image=args.image)
    os.execv(
        str(caddy_binary),
        [str(caddy_binary), "run", "--config", str(config_path), "--adapter", "caddyfile"],
    )


def _resolve_caddy_binary(*, config_path: Path, image: str) -> Path:
    installed = shutil.which("caddy")
    if installed:
        return Path(installed)

    output_dir = config_path.parent / "caddy-bin"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "caddy"
    if output_path.exists():
        output_path.chmod(0o755)
        return output_path

    container_name = f"dtb-caddy-extract-{uuid4().hex[:12]}"
    try:
        _run(["docker", "create", "--name", container_name, image], timeout_seconds=30)
        _run(["docker", "cp", f"{container_name}:/usr/bin/caddy", str(output_path)], timeout_seconds=30)
    finally:
        subprocess.run(["docker", "rm", "-f", container_name], check=False, stdout=subprocess.DEVNULL)
    output_path.chmod(0o755)
    return output_path


def _run(argv: list[str], *, timeout_seconds: float) -> None:
    result = subprocess.run(
        argv,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=timeout_seconds,
    )
    if result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip() or "command failed"
        raise RuntimeError(message)


if __name__ == "__main__":
    main()
