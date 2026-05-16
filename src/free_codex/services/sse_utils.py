"""Advanced SSE utilities for robust streaming, thinking models, and error handling."""

from __future__ import annotations

import asyncio
import errno
import json
import logging
import os
import datetime
import re
import time
from pathlib import Path
from ..utils.free_codex_paths import free_codex_dir
from typing import Any, AsyncGenerator, AsyncIterable, Callable, Optional

logger = logging.getLogger("free-codex.sse")


class UsageTracker:
    """Extended token usage tracker with thinking token support."""
    def __init__(self):
        self._lock = asyncio.Lock()
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.thinking_tokens = 0  # For reasoning models like DeepSeek
        self.total_tokens = 0
        self.requests = 0
        # Load persisted monthly totals on startup
        try:
            db = _load_usage_db()
            month = datetime.date.today().isoformat()[:7]
            monthly = db.get("monthly", {}).get(month, {})
            self.prompt_tokens = monthly.get("prompt_tokens", 0)
            self.completion_tokens = monthly.get("completion_tokens", 0)
            self.thinking_tokens = monthly.get("thinking_tokens", 0)
            self.total_tokens = monthly.get("total_tokens", 0)
            self.requests = monthly.get("requests", 0)
        except Exception:
            pass

    async def add_usage(self, usage):
        async with self._lock:
            self.requests += 1
            if "prompt_tokens" in usage:
                self.prompt_tokens += usage["prompt_tokens"]
            if "completion_tokens" in usage:
                self.completion_tokens += usage["completion_tokens"]
            if "thinking_tokens" in usage:
                self.thinking_tokens += usage["thinking_tokens"]
            if "total_tokens" in usage:
                self.total_tokens += usage["total_tokens"]
            if "total_tokens" not in usage and "prompt_tokens" in usage and "completion_tokens" in usage:
                self.total_tokens += usage["prompt_tokens"] + usage["completion_tokens"]
            # Persist to DB in background
            try:
                record_usage_to_db({
                    "prompt_tokens": usage.get("prompt_tokens", 0),
                    "completion_tokens": usage.get("completion_tokens", 0),
                    "thinking_tokens": usage.get("thinking_tokens", 0),
                    "total_tokens": usage.get("total_tokens", 0),
                })
            except Exception:
                pass

    async def get_stats(self):
        async with self._lock:
            return {
                "requests": self.requests,
                "prompt_tokens": self.prompt_tokens,
                "completion_tokens": self.completion_tokens,
                "thinking_tokens": self.thinking_tokens,
                "total_tokens": self.total_tokens,
            }

    async def reset(self):
        async with self._lock:
            self.prompt_tokens = 0
            self.completion_tokens = 0
            self.thinking_tokens = 0
            self.total_tokens = 0
            self.requests = 0

usage_tracker = UsageTracker()


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
    raw = os.getenv("FREE_CODEX_SSE_HEARTBEAT_SECS", "25")
    try:
        return float(raw)
    except ValueError:
        return 25.0


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


def encode_sse_raw(data_str: str) -> bytes:
    """Encode raw string as SSE message."""
    return f"data: {data_str}\n\n".encode("utf-8")


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
    """Wrap SSE stream with heartbeat comments to keep connection alive during long requests."""
    if interval is None:
        interval = sse_heartbeat_interval()

    if interval <= 0:
        async for chunk in inner:
            yield chunk
        return

    heartbeat_task: asyncio.Task | None = None
    stop_event: asyncio.Event | None = asyncio.Event()

    async def heartbeat_loop() -> None:
        while not stop_event.is_set():
            await asyncio.sleep(interval)
            if not stop_event.is_set():
                try:
                    # Different heartbeat formats for compatibility
                    yield encode_sse_comment(f"heartbeat {time.time()}")
                except Exception:
                    break

    try:
        heartbeat_task = asyncio.create_task(heartbeat_loop())
        async for chunk in sse_disconnect_safe(inner):
            yield chunk
    finally:
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
    - Standard: data: {...}\n\n
    - CR-LF: data: {...}\r\n\r\n
    - DeepSeek: thinking block followed by content
    - Qwen3/Reasoning: reasoning_content field
    - Claude: mixed content blocks
    - [DONE] / data: [DONE] markers
    - Non-standard: raw JSON without SSE wrapper
    """
    buf = b""
    async for chunk in byte_stream:
        if not chunk:
            continue
        buf += chunk

        # Handle both \n\n and \r\n\r\n delimiters
        while True:
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
                    event = json.loads(ds)
                    yield event
                except json.JSONDecodeError:
                    # Try to handle non-SSE JSON (some providers send raw JSON)
                    logger.warning(f"Non-SSE JSON attempt: {ds[:100]}")
                    continue

    # Handle raw JSON fallback (some providers don't use SSE format)
    if buf.strip():
        try:
            raw = buf.decode("utf-8", errors="replace").strip()
            if raw and raw != "[DONE]":
                event = json.loads(raw)
                yield event
        except json.JSONDecodeError:
            # Try parsing each line
            for line in buf.split(b"\n"):
                line = line.strip()
                if line and line != b"[DONE]" and line.startswith(b"{"):
                    try:
                        yield json.loads(line.decode("utf-8", errors="replace"))
                    except json.JSONDecodeError:
                        continue


def extract_thinking_from_event(event: dict[str, Any]) -> Optional[str]:
    """Extract thinking/reasoning content from model events.

    Handles multiple formats:
    - DeepSeek: thinking block in content or separate field
    - Qwen3: reasoning_content in delta
    - Claude: thinking blocks
    """
    choices = event.get("choices") or []
    for choice in choices:
        delta = choice.get("delta") or {}

        # Qwen3 / Thinking models format
        if "reasoning_content" in delta:
            rc = delta["reasoning_content"]
            if rc:
                return rc

        # Content blocks with thinking type
        content = delta.get("content")
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict):
                    btype = block.get("type", "")
                    # DeepSeek thinking
                    if btype == "thinking" or btype == "reasoning":
                        return block.get("thinking") or block.get("text", "")
                    # General reasoning format
                    if "thinking" in str(btype).lower():
                        return block.get("text", "")

        # Check annotation/thought field
        if "thought" in delta:
            return delta["thought"]
        if "thoughts" in delta:
            return delta["thoughts"]

    return None


def strip_thinking_content(full_text: str) -> str:
    """Remove thinking tags from model output to get clean response.

    Strips common thinking tags like:
    - <think>...</think>
    - <reasoning>...</reasoning>
    - [THINKING]...[/THINKING]
    - <!-- reasoning -->...<!-- /reasoning -->
    """
    patterns = [
        r'<think>.*?</think>',
        r'<reasoning>.*?</reasoning>',
        r'\[THINKING\].*?\[/THINKING\]',
        r'<!--\s*reasoning\s*-->.*?<!--\s*/reasoning\s*-->',
        r'<thinking>.*?</thinking>',
        r'<THINKING>.*?</THINKING>',
    ]

    result = full_text
    for pattern in patterns:
        result = re.sub(pattern, '', result, flags=re.IGNORECASE | re.DOTALL)

    return result.strip()


def normalize_content_for_codex(content: Any) -> Optional[str]:
    """Normalize content from various formats to a string.

    Handles:
    - String content
    - List of text blocks
    - Nested content structures
    - Thinking blocks
    """
    if content is None:
        return None

    if isinstance(content, str):
        return content

    if isinstance(content, list):
        text_parts = []
        for block in content:
            if not isinstance(block, dict):
                continue

            btype = block.get("type", "text")
            text = block.get("text") or block.get("content") or ""

            # Skip thinking blocks - they'll be handled separately
            if btype in ("thinking", "reasoning", "thought"):
                continue

            if text:
                text_parts.append(str(text))

        return "\n".join(text_parts) if text_parts else None

    if isinstance(content, dict):
        # Direct text field
        if "text" in content:
            return content["text"]
        if "content" in content:
            return content["content"]
        if "message" in content:
            msg = content["message"]
            if isinstance(msg, dict):
                return msg.get("content") or msg.get("text")
            return str(msg)

    return str(content) if content else None


async def iter_text_deltas(text: str) -> AsyncGenerator[str, None]:
    """Async generator for text deltas with proper chunking."""
    if not text:
        yield ""
        return
    step = sse_chunk_size()
    for i in range(0, len(text), step):
        yield text[i : i + step]


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
                "message": f"Stream timed out after {timeout} seconds. Try increasing FREE_CODEX_READ_TIMEOUT.",
            },
        )
        yield b"data: [DONE]\n\n"


def extract_stream_content(event: dict[str, Any]) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """Extract content, role, and thinking from a chat completion delta event.

    Returns: (content, role, thinking) tuple. Any may be None.
    """
    if event.get("done"):
        return None, None, None

    content = None
    role = None
    thinking = None

    choices = event.get("choices") or []
    for choice in choices:
        delta = choice.get("delta") or {}

        # Extract content
        if "content" in delta:
            content = delta["content"]

        # Extract role
        if "role" in delta:
            role = delta["role"]

        # Extract thinking/reasoning (Qwen3, DeepSeek style)
        if "reasoning_content" in delta:
            thinking = delta["reasoning_content"]

    return content, role, thinking


def extract_usage_from_event(event: dict[str, Any]) -> Optional[dict[str, Any]]:
    """Extract usage information from a completion event."""
    # Check standard usage field
    if "usage" in event:
        return event["usage"]

    # Check completion_details (some providers)
    if "completion_details" in event:
        details = event["completion_details"]
        if isinstance(details, dict) and "usage" in details:
            return details["usage"]

    return None


def is_error_event(event: dict[str, Any]) -> bool:
    """Check if an event represents an error."""
    if isinstance(event, dict):
        if "error" in event:
            return True
        error_type = event.get("type", "")
        if "error" in error_type.lower():
            return True
    return False


async def track_usage_and_forward(
    stream: AsyncGenerator[bytes, None]
) -> AsyncGenerator[bytes, None]:
    """Yield chunks unchanged while parsing SSE events to track token usage."""
    buf = b""
    async for chunk in stream:
        if chunk:
            yield chunk
            buf += chunk
            # Process complete events from buffer
            while True:
                idx = buf.find(b"\n\n")
                crlf_idx = buf.find(b"\r\n\r\n")
                if crlf_idx >= 0 and (idx < 0 or crlf_idx < idx):
                    pos = crlf_idx
                    delim_len = 4
                elif idx >= 0:
                    pos = idx
                    delim_len = 2
                else:
                    break
                event_bytes = buf[:pos]
                buf = buf[pos + delim_len:]
                if not event_bytes:
                    continue
                # Parse event lines for usage
                for line in event_bytes.split(b"\n"):
                    if line.startswith(b"\r"):
                        line = line[1:]
                    if not line.startswith(b"data: "):
                        continue
                    data_str = line[6:].decode("utf-8", errors="replace").strip()
                    if not data_str or data_str == "[DONE]":
                        continue
                    try:
                        data = json.loads(data_str)
                        if "usage" in data:
                            asyncio.create_task(usage_tracker.add_usage(data["usage"]))
                    except json.JSONDecodeError:
                        logger.warning(f"Failed to parse SSE for usage tracking: {data_str[:100]}")
                        continue
        else:
            yield chunk
    # Process any remaining data after stream ends
    if buf:
        for line in buf.split(b"\n"):
            if line.startswith(b"\r"):
                line = line[1:]
            if not line.startswith(b"data: "):
                continue
            data_str = line[6:].decode("utf-8", errors="replace").strip()
            if not data_str or data_str == "[DONE]":
                continue
            try:
                data = json.loads(data_str)
                if "usage" in data:
                    asyncio.create_task(usage_tracker.add_usage(data["usage"]))
            except json.JSONDecodeError:
                pass

# Pricing per 1M tokens
PRICING_INPUT = 5.0      # $5 per 1M input tokens
PRICING_OUTPUT = 30.0   # $30 per 1M output tokens
PRICING_CACHE_INPUT = 0.5  # $0.5 per 1M cached input tokens


def _usage_stats_dir() -> Path:
    d = free_codex_dir() / "usage_stats"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _usage_db_path() -> Path:
    return _usage_stats_dir() / "usage.json"


def _load_usage_db() -> dict[str, Any]:
    p = _usage_db_path()
    if p.exists():
        try:
            with p.open("r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {"daily": {}, "monthly": {}, "first_date": None, "last_date": None}
    return {"daily": {}, "monthly": {}, "first_date": None, "last_date": None}


def _save_usage_db(db: dict[str, Any]) -> None:
    p = _usage_db_path()
    p.write_text(json.dumps(db, indent=2), encoding="utf-8")


def record_usage_to_db(usage: dict[str, int]) -> None:
    """Persist usage stats by day and month with streak tracking."""
    try:
        db = _load_usage_db()
        today = datetime.date.today().isoformat()
        month = today[:7]

        # Initialize entries if missing
        if today not in db.get("daily", {}):
            db.setdefault("daily", {})[today] = {
                "requests": 0,
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "thinking_tokens": 0,
                "total_tokens": 0,
            }
        if month not in db.get("monthly", {}):
            db.setdefault("monthly", {})[month] = {
                "requests": 0,
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "thinking_tokens": 0,
                "total_tokens": 0,
            }

        # Update counters
        daily = db["daily"][today]
        monthly = db["monthly"][month]
        daily["requests"] += 1
        monthly["requests"] += 1
        if "prompt_tokens" in usage:
            pt = usage["prompt_tokens"]
            daily["prompt_tokens"] += pt
            monthly["prompt_tokens"] += pt
        if "completion_tokens" in usage:
            ct = usage["completion_tokens"]
            daily["completion_tokens"] += ct
            monthly["completion_tokens"] += ct
        if "thinking_tokens" in usage:
            tt = usage["thinking_tokens"]
            daily["thinking_tokens"] = daily.get("thinking_tokens", 0) + tt
            monthly["thinking_tokens"] = monthly.get("thinking_tokens", 0) + tt
        if "total_tokens" in usage:
            tt = usage["total_tokens"]
            daily["total_tokens"] += tt
            monthly["total_tokens"] += tt
        if "total_tokens" not in usage and "prompt_tokens" in usage and "completion_tokens" in usage:
            daily["total_tokens"] = daily.get("prompt_tokens", 0) + daily.get("completion_tokens", 0)
            monthly["total_tokens"] = monthly.get("prompt_tokens", 0) + monthly.get("completion_tokens", 0)

        db["last_date"] = today
        if db.get("first_date") is None:
            db["first_date"] = today

        _save_usage_db(db)
    except Exception:
        pass


def get_persistent_stats() -> dict[str, Any]:
    """Return combined daily, monthly, and streak stats."""
    db = _load_usage_db()
    today = datetime.date.today().isoformat()
    month = today[:7]

    daily = db.get("daily", {}).get(today, {
        "requests": 0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "thinking_tokens": 0,
        "total_tokens": 0,
    })
    monthly = db.get("monthly", {}).get(month, {
        "requests": 0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "thinking_tokens": 0,
        "total_tokens": 0,
    })

    # Streak: consecutive days with at least one request
    streak = 0
    try:
        daily_db = db.get("daily", {})
        d = datetime.date.today()
        while True:
            iso = d.isoformat()
            entry = daily_db.get(iso)
            if entry and entry.get("requests", 0) > 0:
                streak += 1
                d -= datetime.timedelta(days=1)
            else:
                break
    except Exception:
        streak = 0

    # All-time totals
    all_ = {"requests": 0, "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "thinking_tokens": 0}
    for day_entry in db.get("daily", {}).values():
        all_["requests"] += day_entry.get("requests", 0)
        all_["prompt_tokens"] += day_entry.get("prompt_tokens", 0)
        all_["completion_tokens"] += day_entry.get("completion_tokens", 0)
        all_["total_tokens"] += day_entry.get("total_tokens", 0)
        all_["thinking_tokens"] = all_.get("thinking_tokens", 0) + day_entry.get("thinking_tokens", 0)

    # Compute costs using pricing ($/1M tokens)
    def compute_cost(prompt, completion, total):
        return (prompt * PRICING_INPUT / 1_000_000) + (completion * PRICING_OUTPUT / 1_000_000)

    return {
        "all_time": all_,
        "today": daily,
        "monthly": monthly,
        "streak_days": streak,
        "cost_all_time": compute_cost(all_["prompt_tokens"], all_["completion_tokens"], all_["total_tokens"]),
        "cost_today": compute_cost(daily["prompt_tokens"], daily["completion_tokens"], daily["total_tokens"]),
        "cost_monthly": compute_cost(monthly["prompt_tokens"], monthly["completion_tokens"], monthly["total_tokens"]),
    }