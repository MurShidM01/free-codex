"""fc-server entrypoint with clean shutdown on Ctrl+C and optional auto-reload."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import free_codex
import uvicorn

from .app import create_app
from .utils.config import settings


def _reload_enabled() -> bool:
    """Watch Python + admin static files; set FREE_CODEX_RELOAD=0 to disable."""
    v = os.getenv("FREE_CODEX_RELOAD", "").strip().lower()
    return v in ("1", "true", "yes", "on")


def _package_root() -> Path:
    return Path(free_codex.__file__).resolve().parent


def run_server() -> None:
    port = settings.server_port
    host = settings.server_host
    print(f"\n  Admin UI (local): http://127.0.0.1:{port}/admin\n", flush=True)
    reload = _reload_enabled()
    if reload:
        pkg = _package_root()
        print(
            "  FREE_CODEX_RELOAD is on — code & /admin static files reload on change.\n",
            flush=True,
        )
        try:
            uvicorn.run(
                "free_codex.app:create_app",
                factory=True,
                host=host,
                port=port,
                log_level="info",
                reload=True,
                reload_dirs=[str(pkg)],
                reload_includes=["*.py", "*.html", "*.js", "*.css"],
            )
        except KeyboardInterrupt:
            sys.exit(0)
        return

    config = uvicorn.Config(
        create_app(),
        host=host,
        port=port,
        log_level="info",
        timeout_graceful_shutdown=5,
    )
    server = uvicorn.Server(config)
    try:
        server.run()
    except KeyboardInterrupt:
        sys.exit(0)
