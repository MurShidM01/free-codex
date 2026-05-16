"""Launch Codex CLI with Free Codex config and preflight checks."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from typing import Optional

from .utils.free_codex_paths import (
    default_server_health_url,
    free_codex_config_toml,
    free_codex_dir,
)


def resolve_codex_executable() -> Optional[str]:
    return shutil.which("codex")


def _proxy_healthy(url: str, timeout: float = 2.0) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            if resp.getcode() != 200:
                return False
            data = json.loads(resp.read().decode("utf-8"))
            return data.get("status") == "healthy"
    except (OSError, urllib.error.URLError, json.JSONDecodeError, ValueError):
        return False


def run_codex() -> None:
    cfg = free_codex_config_toml()
    if not cfg.is_file():
        print(f"Error: missing {cfg}. Run fc-init first.")
        sys.exit(2)

    health_url = os.getenv("FREE_CODEX_HEALTH_URL") or default_server_health_url()
    if not _proxy_healthy(health_url):
        print(
            "Error: fc-server is not running or not reachable at "
            f"{health_url}. Start fc-server first (match FREE_CODEX_PORT if set)."
        )
        sys.exit(3)

    codex = resolve_codex_executable()
    if not codex:
        print("Error: 'codex' command not found. Install the OpenAI Codex CLI.")
        sys.exit(1)

    env = os.environ.copy()
    env["CODEX_HOME"] = str(free_codex_dir().resolve())

    proc = subprocess.Popen([codex, *sys.argv[1:]], env=env)
    try:
        rc = proc.wait()
    except KeyboardInterrupt:
        proc.terminate()
        try:
            proc.wait(timeout=8)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=3)
        sys.exit(130)

    sys.exit(rc)
