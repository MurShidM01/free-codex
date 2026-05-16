"""SSE framing for OpenAI Responses-style streams."""

from __future__ import annotations

import json
from typing import Any


def encode_sse(event: str, data: dict[str, Any]) -> bytes:
    line = json.dumps(data, separators=(",", ":"), ensure_ascii=False)
    return f"event: {event}\ndata: {line}\n\n".encode("utf-8")
