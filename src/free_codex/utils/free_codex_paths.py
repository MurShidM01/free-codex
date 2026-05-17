"""Canonical config location for fc-init / fc-codex / fc-server (not ~/.codex)."""

from __future__ import annotations

import os
from pathlib import Path


def free_codex_dir() -> Path:
    return Path.home() / ".config" / "free-codex"


def free_codex_config_toml() -> Path:
    return free_codex_dir() / "config.toml"


def free_codex_dotenv() -> Path:
    return free_codex_dir() / ".env"


def default_server_health_url() -> str:
    port = int(os.getenv("FREE_CODEX_PORT", "8080"))
    host = os.getenv("FREE_CODEX_HEALTH_HOST", "127.0.0.1")
    return f"http://{host}:{port}/health/json"
