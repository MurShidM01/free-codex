"""Buffered SSE for non-streaming NIM completions converted to SSE responses."""

from __future__ import annotations

import uuid
import json
from typing import Any, AsyncGenerator

from .responses_bridge import (
    build_completed_response,
    chat_completion_assistant_content,
    response_skeleton,
)
from .responses_output_items import output_from_chat_completion
from .responses_sse_codec import encode_sse


_LOGPROBS: list[dict[str, Any]] = []


def _make_ids() -> tuple[str, str]:
    suffix = uuid.uuid4().hex[:24]
    return f"fc_{suffix}", f"msg_{suffix}"


class _Seq:
    """Simple sequence counter for SSE events."""

    __slots__ = ("_n",)

    def __init__(self) -> None:
        self._n = 0

    def next(self) -> int:
        n = self._n
        self._n += 1
        return n


def _message_item_text(item: dict[str, Any]) -> str:
    """Extract text from a message item's content blocks."""
    parts: list[str] = []
    for block in item.get("content") or []:
        if isinstance(block, dict) and block.get("type") == "output_text":
            t = block.get("text")
            if isinstance(t, str):
                parts.append(t)
    return "".join(parts)


def _iter_text_chunks(text: str, chunk_size: int = 1536) -> list[str]:
    """Split text into chunks for SSE streaming."""
    if not text:
        return [""]
    return [text[i : i + chunk_size] for i in range(0, len(text), chunk_size)]


async def _emit_assistant_message_sse(
    *,
    msg_id: str,
    output_index: int,
    text: str,
    seq: _Seq,
) -> AsyncGenerator[bytes, None]:
    """Emit SSE events for a complete assistant message."""
    # Output item added
    yield encode_sse(
        "response.output_item.added",
        {
            "type": "response.output_item.added",
            "output_index": output_index,
            "sequence_number": seq.next(),
            "item": {
                "id": msg_id,
                "type": "message",
                "status": "in_progress",
                "role": "assistant",
                "content": [],
            },
        },
    )

    # Content part added
    yield encode_sse(
        "response.content_part.added",
        {
            "type": "response.content_part.added",
            "item_id": msg_id,
            "output_index": output_index,
            "content_index": 0,
            "sequence_number": seq.next(),
            "part": {"type": "output_text", "text": "", "annotations": []},
        },
    )

    # Text deltas
    for piece in _iter_text_chunks(text):
        yield encode_sse(
            "response.output_text.delta",
            {
                "type": "response.output_text.delta",
                "item_id": msg_id,
                "output_index": output_index,
                "content_index": 0,
                "delta": piece,
                "logprobs": _LOGPROBS,
                "sequence_number": seq.next(),
            },
        )

    # Text done
    yield encode_sse(
        "response.output_text.done",
        {
            "type": "response.output_text.done",
            "item_id": msg_id,
            "output_index": output_index,
            "content_index": 0,
            "text": text,
            "logprobs": _LOGPROBS,
            "sequence_number": seq.next(),
        },
    )

    # Content part done
    yield encode_sse(
        "response.content_part.done",
        {
            "type": "response.content_part.done",
            "item_id": msg_id,
            "output_index": output_index,
            "content_index": 0,
            "sequence_number": seq.next(),
            "part": {
                "type": "output_text",
                "text": text,
                "annotations": [],
            },
        },
    )

    # Output item done
    yield encode_sse(
        "response.output_item.done",
        {
            "type": "response.output_item.done",
            "output_index": output_index,
            "sequence_number": seq.next(),
            "item": {
                "id": msg_id,
                "type": "message",
                "status": "completed",
                "role": "assistant",
                "content": [
                    {"type": "output_text", "text": text, "annotations": []}
                ],
            },
        },
    )


async def _emit_function_call_sse(
    *,
    item: dict[str, Any],
    output_index: int,
    seq: _Seq,
) -> AsyncGenerator[bytes, None]:
    """Emit SSE events for a function call."""
    iid = str(item.get("id") or f"fc_{uuid.uuid4().hex[:16]}")
    name = str(item.get("name") or "")
    args = str(item.get("arguments") or "{}")
    call_id = str(item.get("call_id") or "")

    # Output item added
    yield encode_sse(
        "response.output_item.added",
        {
            "type": "response.output_item.added",
            "output_index": output_index,
            "sequence_number": seq.next(),
            "item": {
                "type": "function_call",
                "id": iid,
                "call_id": call_id,
                "name": name,
                "arguments": "",
                "status": "in_progress",
            },
        },
    )

    # Arguments deltas
    for piece in _iter_text_chunks(args):
        yield encode_sse(
            "response.function_call_arguments.delta",
            {
                "type": "response.function_call_arguments.delta",
                "item_id": iid,
                "output_index": output_index,
                "delta": piece,
                "sequence_number": seq.next(),
            },
        )

    # Arguments done
    yield encode_sse(
        "response.function_call_arguments.done",
        {
            "type": "response.function_call_arguments.done",
            "item_id": iid,
            "output_index": output_index,
            "name": name,
            "arguments": args,
            "sequence_number": seq.next(),
        },
    )

    # Output item done
    yield encode_sse(
        "response.output_item.done",
        {
            "type": "response.output_item.done",
            "output_index": output_index,
            "sequence_number": seq.next(),
            "item": {
                "type": "function_call",
                "id": iid,
                "call_id": call_id,
                "name": name,
                "arguments": args,
                "status": "completed",
            },
        },
    )


async def minimal_sse_from_completion(
    completion: dict[str, Any],
    *,
    resp_id: str,
    msg_id: str,
    displayed_model: str,
    req_body: dict[str, Any],
) -> AsyncGenerator[bytes, None]:
    """Convert a non-streaming NIM completion into Responses SSE stream.

    This is used when streaming is requested but the underlying API
    doesn't support it, so we buffer the full response and stream it.

    Args:
        completion: Complete chat completion response from NIM
        resp_id: Response ID for the SSE stream
        msg_id: Message ID for the SSE stream
        displayed_model: Model name to display in response
        req_body: Original request body for metadata
    """
    seq = _Seq()
    skel = response_skeleton(resp_id, displayed_model, req_body)

    # Emit response events
    yield encode_sse(
        "response.created",
        {
            "type": "response.created",
            "sequence_number": seq.next(),
            "response": skel,
        },
    )
    yield encode_sse(
        "response.in_progress",
        {
            "type": "response.in_progress",
            "sequence_number": seq.next(),
            "response": skel,
        },
    )

    # Extract output items from completion
    out = output_from_chat_completion(completion)

    if not out:
        # Simple text response
        text = chat_completion_assistant_content(completion)
        async for chunk in _emit_assistant_message_sse(
            msg_id=msg_id, output_index=0, text=text, seq=seq
        ):
            yield chunk
    else:
        # Process each output item (message or function_call)
        idx = 0
        for item in out:
            typ = item.get("type")
            if typ == "message":
                mid = str(item.get("id") or f"{msg_id}_{idx}")
                txt = _message_item_text(item)
                async for chunk in _emit_assistant_message_sse(
                    msg_id=mid, output_index=idx, text=txt, seq=seq
                ):
                    yield chunk
                idx += 1
            elif typ == "function_call":
                async for chunk in _emit_function_call_sse(
                    item=item, output_index=idx, seq=seq
                ):
                    yield chunk
                idx += 1

    # Build and emit final response
    final = build_completed_response(
        resp_id=resp_id,
        msg_id=msg_id,
        model=displayed_model,
        req_body=req_body,
        assistant_text="",
        cc=completion,
        output=out if out else None,
    )
    yield encode_sse(
        "response.completed",
        {
            "type": "response.completed",
            "sequence_number": seq.next(),
            "response": final,
        },
    )