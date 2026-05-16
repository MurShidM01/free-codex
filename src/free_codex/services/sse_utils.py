"""Advanced SSE utilities for robust streaming and error handling."""

from __future__ import annotations

import asyncio
import errno
import json
import logging
import os
from typing import Any, AsyncGenerator, AsyncIterable, Callable, Optional

logger = logging.getLogger("free-codex.sse")


# SSE chunk size configuration
def sse_chunk_size() -> int:
    """Get SSE chunk size from environment."""
    raw = os.getenv("FREE_CODEX_SSE_DELTA_CHARS", "1536")
    try:
        n = int(raw)
    except ValueError:
        n = 1536
    return max(256, min(n, 32768))


def sse_heartbeat_interval() -> float:
    """Get heartbeat interval in seconds (0 to disable)."""
    raw = os.getenv("FREE_CODEX_SSE_HEARTBEAT_SECS", "30")
    try:
        return float(raw)
    except ValueError:
        return 30.0


def iter_text_deltas(text: str) -> list[str]:
    """Split text into SSE-friendly chunks."""
    if not text:
        return []
    step = sse_chunk_size()
    return [text[i : i + step] for i in range(0, len(text), step)]


def encode_sse(event: str, data: dict[str, Any]) -> bytes:
    """Encode data as SSE message."""
    line = json.dumps(data, separators=(",", ":"), ensure_ascii=False)
    return f"event: {event}\ndata: {line}\n\n".encode("utf-8")


def encode_sse_comment(comment: str) -> bytes:
    """Encode a comment line (for keepalive)."""
    return f": {comment}\n\n".encode("utf-8")


async def sse_disconnect_safe(
    inner: AsyncGenerator[bytes, None],
) -> AsyncGenerator[bytes, None]:
    """Safely iterate SSE chunks, handling disconnects gracefully."""
    try:
        async for chunk in inner:
            yield chunk
    except asyncio.CancelledError:
        logger.debug("SSE stream cancelled by client")
        raise
    except OSError as e:
        win_err = getattr(e, "winerror", None)
        if win_err == 10054:
            logger.debug("Client disconnected (WinError 10054)")
            return
        if getattr(e, "errno", None) in (
            errno.ECONNRESET,
            errno.EPIPE,
            errno.ECONNABORTED,
        ):
            logger.debug("Connection reset by peer")
            return
        logger.warning(f"SSE stream OS error: {e}")
        raise


async def sse_with_heartbeat(
    inner: AsyncGenerator[bytes, None],
    interval: float | None = None,
) -> AsyncGenerator[bytes, None]:
    """Wrap SSE stream with heartbeat comments to keep connection alive."""
    if interval is None:
        interval = sse_heartbeat_interval()

    if interval <= 0:
        async for chunk in inner:
            yield chunk
        return

    heartbeat_task: asyncio.Task | None = None
    stop_event: asyncio.Event | None = None

    async def heartbeat_loop() -> None:
        if stop_event is None:
            return
        while not stop_event.is_set():
            await asyncio.sleep(interval)
            if not stop_event.is_set():
                try:
                    yield encode_sse_comment("heartbeat")
                except Exception:
                    break

    try:
        heartbeat_task = asyncio.create_task(heartbeat_loop())
        async for chunk in sse_disconnect_safe(inner):
            yield chunk
    finally:
        if stop_event is not None:
            stop_event.set()
        if heartbeat_task is not None:
            heartbeat_task.cancel()
            try:
                await heartbeat_task
            except asyncio.CancelledError:
                pass


async def iter_openai_chat_sse(
    byte_stream: AsyncIterable[bytes],
) -> AsyncGenerator[dict[str, Any], None]:
    """Parse OpenAI-style SSE stream into events.

    Handles multiple formats:
    - data: {...}\n\n
    - data: {...}\r\n\r\n
    - [DONE] marker
    - Mixed line endings
    """
    buf = b""
    async for chunk in byte_stream:
        if not chunk:
            continue
        buf += chunk

        # Handle both \n\n and \r\n\r\n delimiters
        while True:
            # Try double newline first
            idx = buf.find(b"\n\n")
            crlf_idx = buf.find(b"\r\n\r\n")
            if crlf_idx >= 0 and (idx < 0 or crlf_idx < idx):
                idx = crlf_idx
                delimiter_len = 4
            elif idx >= 0:
                delimiter_len = 2
            else:
                break

            block, buf = buf[:idx], buf[idx + delimiter_len:]

            # Process each line in the block
            for raw_line in block.split(b"\n"):
                if raw_line.startswith(b"\r"):
                    raw_line = raw_line[1:]
                if not raw_line.startswith(b"data: "):
                    continue

                ds = raw_line[6:].decode("utf-8", errors="replace").strip()
                if not ds or ds == "[DONE]":
                    yield {"done": True}
                    return

                try:
                    yield json.loads(ds)
                except json.JSONDecodeError:
                    logger.warning(f"Failed to parse SSE data: {ds[:100]}")
                    continue

    # Handle any remaining data
    for raw_line in buf.split(b"\n"):
        if raw_line.startswith(b"\r"):
            raw_line = raw_line[1:]
        if not raw_line.startswith(b"data: "):
            continue
        ds = raw_line[6:].decode("utf-8", errors="replace").strip()
        if ds == "[DONE]" or not ds:
            yield {"done": True}
            return
        try:
            yield json.loads(ds)
        except json.JSONDecodeError:
            continue


async def yield_error_sse(error_message: str, error_type: str = "server_error") -> bytes:
    """Generate an error SSE response."""
    return encode_sse(
        "error",
        {
            "type": error_type,
            "message": error_message,
        },
    )


class SSEBuffer:
    """Buffer for assembling SSE chunks with proper retry handling."""

    def __init__(self, flush_interval: float = 0.01):
        self._buffer: list[bytes] = []
        self._flush_interval = flush_interval
        self._last_yield: float = 0

    async def add(self, chunk: bytes) -> None:
        """Add a chunk to the buffer."""
        self._buffer.append(chunk)

    async def flush(self) -> AsyncGenerator[bytes, None]:
        """Yield and clear buffered chunks."""
        if self._buffer:
            yield b"".join(self._buffer)
            self._buffer.clear()

    def clear(self) -> None:
        """Clear the buffer without yielding."""
        self._buffer.clear()


async def stream_with_timeout(
    inner: AsyncGenerator[bytes, None],
    timeout: float = 120.0,
) -> AsyncGenerator[bytes, None]:
    """Stream with automatic timeout for stuck connections."""
    try:
        async for chunk in asyncio.wait_for(inner.__anext__(), timeout=timeout):
            yield chunk
    except asyncio.TimeoutError:
        logger.warning(f"SSE stream timed out after {timeout}s")
        yield encode_sse(
            "error",
            {
                "type": "timeout",
                "message": f"Stream timed out after {timeout} seconds",
            },
        )
        yield b"data: [DONE]\n\n"


def extract_stream_content(event: dict[str, Any]) -> tuple[Optional[str], Optional[str]]:
    """Extract content and role from a chat completion delta event.

    Returns: (content, role) tuple. Either may be None.
    """
    if event.get("done"):
        return None, None

    content = None
    role = None

    choices = event.get("choices") or []
    for choice in choices:
        delta = choice.get("delta") or {}
        if "content" in delta:
            content = delta["content"]
        if "role" in delta:
            role = delta["role"]

    return content, role


def extract_usage_from_event(event: dict[str, Any]) -> Optional[dict[str, Any]]:
    """Extract usage information from a completion event."""
    return event.get("usage")


def is_error_event(event: dict[str, Any]) -> bool:
    """Check if an event represents an error."""
    if isinstance(event, dict):
        if "error" in event:
            return True
        error_type = event.get("type", "")
        if "error" in error_type.lower():
            return True
    return False