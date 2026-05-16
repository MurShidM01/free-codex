"""Reduce asyncio noise when HTTP/SSE clients reset sockets (common on Windows)."""

from __future__ import annotations

import logging


class AsyncioTransportResetFilter(logging.Filter):
    """Drop Proactor pipe shutdown callbacks after Codex closes streams early."""

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        if "Exception in callback" in msg and "_call_connection_lost" in msg:
            return False
        if "WinError 10054" in msg and "_call_connection_lost" in msg:
            return False
        return True


def install_asyncio_noise_filter() -> None:
    logging.getLogger("asyncio").addFilter(AsyncioTransportResetFilter())
