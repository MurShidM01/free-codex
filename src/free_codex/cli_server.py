"""fc-server entrypoint with clean shutdown on Ctrl+C."""

from __future__ import annotations

import sys

import uvicorn

from .app import create_app
from .utils.config import settings


def run_server() -> None:
    port = settings.server_port
    print(f"\n  Admin UI (local): http://127.0.0.1:{port}/admin\n", flush=True)
    config = uvicorn.Config(
        create_app(),
        host=settings.server_host,
        port=settings.server_port,
        log_level="info",
        timeout_graceful_shutdown=5,
    )
    server = uvicorn.Server(config)
    try:
        server.run()
    except KeyboardInterrupt:
        sys.exit(0)
