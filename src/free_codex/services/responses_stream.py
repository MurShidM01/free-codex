"""SSE bridging: NIM chat-completions stream -> OpenAI Responses stream events."""

from __future__ import annotations

import json
from typing import Any, AsyncGenerator, AsyncIterable

from .responses_bridge import (
    build_completed_response,
    response_skeleton,
)
from .responses_sse_codec import encode_sse


async def iter_openai_chat_sse(
    byte_stream: AsyncIterable[bytes],
) -> AsyncGenerator[dict[str, Any], None]:
    buf = b""
    async for chunk in byte_stream:
        buf += chunk
        while True:
            idx = buf.find(b"\n\n")
            if idx < 0:
                break
            block, buf = buf[:idx], buf[idx + 2 :]
            for raw_line in block.split(b"\n"):
                if not raw_line.startswith(b"data: "):
                    continue
                ds = raw_line[6:].decode("utf-8", errors="replace").strip()
                if ds == "[DONE]":
                    yield {"done": True}
                    return
                if not ds:
                    continue
                try:
                    yield json.loads(ds)
                except json.JSONDecodeError:
                    continue


def _upstream_error_message(err: Any) -> str:
    if isinstance(err, dict):
        return str(err.get("message") or err.get("code") or json.dumps(err))
    return str(err)


async def stream_responses_body(
    nim_bytes: AsyncIterable[bytes],
    *,
    resp_id: str,
    msg_id: str,
    displayed_model: str,
    req_body: dict[str, Any],
) -> AsyncGenerator[bytes, None]:
    skeleton = response_skeleton(resp_id, displayed_model, req_body)
    yield encode_sse(
        "response.created",
        {"type": "response.created", "response": skeleton},
    )
    yield encode_sse(
        "response.in_progress",
        {"type": "response.in_progress", "response": skeleton},
    )
    yield encode_sse(
        "response.output_item.added",
        {
            "type": "response.output_item.added",
            "output_index": 0,
            "item": {
                "id": msg_id,
                "type": "message",
                "status": "in_progress",
                "role": "assistant",
                "content": [],
            },
        },
    )
    yield encode_sse(
        "response.content_part.added",
        {
            "type": "response.content_part.added",
            "item_id": msg_id,
            "output_index": 0,
            "content_index": 0,
            "part": {"type": "output_text", "text": "", "annotations": []},
        },
    )

    usage_obj: dict[str, Any] | None = None
    full: list[str] = []

    async for ev in iter_openai_chat_sse(nim_bytes):
        if ev.get("done"):
            break
        if "error" in ev:
            msg = _upstream_error_message(ev["error"])
            yield encode_sse(
                "error",
                {
                    "type": "error",
                    "error": {"type": "upstream_error", "message": msg},
                },
            )
            return
        usage_obj = ev.get("usage") or usage_obj
        for choice in ev.get("choices") or []:
            delta = choice.get("delta") or {}
            piece = delta.get("content")
            if piece:
                full.append(piece)
                yield encode_sse(
                    "response.output_text.delta",
                    {
                        "type": "response.output_text.delta",
                        "item_id": msg_id,
                        "output_index": 0,
                        "content_index": 0,
                        "delta": piece,
                    },
                )

    merged = "".join(full)

    yield encode_sse(
        "response.output_text.done",
        {
            "type": "response.output_text.done",
            "item_id": msg_id,
            "output_index": 0,
            "content_index": 0,
            "text": merged,
        },
    )
    yield encode_sse(
        "response.content_part.done",
        {
            "type": "response.content_part.done",
            "item_id": msg_id,
            "output_index": 0,
            "content_index": 0,
            "part": {
                "type": "output_text",
                "text": merged,
                "annotations": [],
            },
        },
    )
    yield encode_sse(
        "response.output_item.done",
        {
            "type": "response.output_item.done",
            "output_index": 0,
            "item": {
                "id": msg_id,
                "type": "message",
                "status": "completed",
                "role": "assistant",
                "content": [
                    {"type": "output_text", "text": merged, "annotations": []}
                ],
            },
        },
    )

    cc = {"usage": usage_obj}
    final = build_completed_response(
        resp_id=resp_id,
        msg_id=msg_id,
        model=displayed_model,
        req_body=req_body,
        assistant_text=merged,
        cc=cc,
    )
    yield encode_sse(
        "response.completed",
        {"type": "response.completed", "response": final},
    )
