"""Split large SSE payloads into Codex-friendly incremental deltas."""

from __future__ import annotations

import os
from typing import Iterator


def sse_chunk_char_size() -> int:
    raw = os.getenv("FREE_CODEX_SSE_DELTA_CHARS", "1536")
    try:
        n = int(raw)
    except ValueError:
        n = 1536
    return max(256, min(n, 32768))


def iter_text_deltas(text: str) -> Iterator[str]:
    """Yield substring chunks (Python str slices are Unicode-safe)."""
    if not text:
        yield ""
        return
    step = sse_chunk_char_size()
    for i in range(0, len(text), step):
        yield text[i : i + step]
