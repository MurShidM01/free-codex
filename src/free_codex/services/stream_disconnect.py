"""Gracefully end SSE streams when the HTTP client disconnects (Windows-safe)."""

from __future__ import annotations

import asyncio
import errno
from typing import AsyncGenerator


async def sse_disconnect_safe(
    inner: AsyncGenerator[bytes, None],
) -> AsyncGenerator[bytes, None]:
    try:
        async for chunk in inner:
            yield chunk
    except asyncio.CancelledError:
        raise
    except OSError as e:
        if getattr(e, "winerror", None) == 10054:
            return
        if getattr(e, "errno", None) in (
            errno.ECONNRESET,
            errno.EPIPE,
            errno.ECONNABORTED,
        ):
            return
        raise
