"""Advanced SSE bridging for OpenAI Responses API streaming."""

from __future__ import annotations

import json
import time
import uuid
from typing import Any, AsyncGenerator, AsyncIterable, Optional

from .responses_bridge import (
    build_completed_response,
    response_skeleton,
)
from .responses_sse_codec import encode_sse
from .sse_utils import iter_openai_chat_sse, sse_chunk_size


_LOGPROBS: list[dict[str, Any]] = []


def _make_ids() -> tuple[str, str]:
    """Generate response and message IDs."""
    suffix = uuid.uuid4().hex[:24]
    return f"fc_{suffix}", f"msg_{suffix}"


class SequenceGenerator:
    """Thread-safe sequence number generator for SSE events."""

    def __init__(self) -> None:
        self._n = 0

    def next(self) -> int:
        n = self._n
        self._n += 1
        return n

    def reset(self) -> None:
        self._n = 0


def _upstream_error_message(err: Any) -> str:
    """Extract human-readable error message from upstream error."""
    if isinstance(err, dict):
        return str(err.get("message") or err.get("code") or json.dumps(err))
    return str(err)


async def iter_text_deltas(text: str) -> AsyncGenerator[str, None]:
    """Async generator for text deltas with proper chunking."""
    if not text:
        yield ""
        return
    step = sse_chunk_size()
    for i in range(0, len(text), step):
        yield text[i : i + step]


async def stream_responses_body(
    nim_bytes: AsyncIterable[bytes],
    *,
    resp_id: str,
    msg_id: str,
    displayed_model: str,
    req_body: dict[str, Any],
) -> AsyncGenerator[bytes, None]:
    """Stream responses body converting NIM SSE to Responses SSE events.

    This handles:
    - Multiple content blocks in a single delta
    - Function calls in tool_calls
    - Proper sequence numbering
    - Role identification
    - Usage tracking
    - Graceful completion
    """
    seq = SequenceGenerator()
    skeleton = response_skeleton(resp_id, displayed_model, req_body)

    # Emit initial response events
    yield encode_sse(
        "response.created",
        {
            "type": "response.created",
            "sequence_number": seq.next(),
            "response": skeleton,
        },
    )
    yield encode_sse(
        "response.in_progress",
        {
            "type": "response.in_progress",
            "sequence_number": seq.next(),
            "response": skeleton,
        },
    )

    usage_obj: dict[str, Any] | None = None
    full_text_parts: list[str] = []
    role_detected: str | None = None
    tool_calls_in_progress: dict[int, dict[str, Any]] = {}
    current_output_index = 0

    async for ev in iter_openai_chat_sse(nim_bytes):
        if ev.get("done"):
            break

        # Handle errors
        if "error" in ev:
            msg = _upstream_error_message(ev["error"])
            yield encode_sse(
                "error",
                {
                    "type": "error",
                    "error": {
                        "type": "upstream_error",
                        "message": msg,
                    },
                },
            )
            return

        # Extract usage when seen
        if "usage" in ev:
            usage_obj = ev["usage"]

        # Process choices
        for choice_idx, choice in enumerate(ev.get("choices") or []):
            delta = choice.get("delta") or {}

            # Handle role detection
            if "role" in delta and role_detected is None:
                role_detected = delta["role"]

            # Handle content delta
            if "content" in delta:
                content = delta["content"]
                if content:
                    if isinstance(content, str):
                        full_text_parts.append(content)

                        # Emit content delta with proper chunking
                        async for piece in iter_text_deltas(content):
                            yield encode_sse(
                                "response.output_text.delta",
                                {
                                    "type": "response.output_text.delta",
                                    "item_id": msg_id,
                                    "output_index": current_output_index,
                                    "content_index": 0,
                                    "delta": piece,
                                    "logprobs": _LOGPROBS,
                                    "sequence_number": seq.next(),
                                },
                            )
                    elif isinstance(content, list):
                        for block in content:
                            if isinstance(block, dict):
                                block_type = block.get("type")
                                block_text = block.get("text", "")
                                if block_type == "text" and block_text:
                                    full_text_parts.append(block_text)
                                    async for piece in iter_text_deltas(block_text):
                                        yield encode_sse(
                                            "response.output_text.delta",
                                            {
                                                "type": "response.output_text.delta",
                                                "item_id": msg_id,
                                                "output_index": current_output_index,
                                                "content_index": 0,
                                                "delta": piece,
                                                "logprobs": _LOGPROBS,
                                                "sequence_number": seq.next(),
                                            },
                                        )
                                # Handle computer_call_output type blocks
                                elif block_type in ("computer_call_output", "function_call_output"):
                                    output_text = block.get("output", block.get("text", ""))
                                    if output_text:
                                        full_text_parts.append(str(output_text))
                                        async for piece in iter_text_deltas(str(output_text)):
                                            yield encode_sse(
                                                "response.output_text.delta",
                                                {
                                                    "type": "response.output_text.delta",
                                                    "item_id": msg_id,
                                                    "output_index": current_output_index,
                                                    "content_index": 0,
                                                    "delta": piece,
                                                    "logprobs": _LOGPROBS,
                                                    "sequence_number": seq.next(),
                                                },
                                            )

            # Handle function calls
            tool_calls = delta.get("tool_calls") or []
            for tc in tool_calls:
                if not isinstance(tc, dict):
                    continue

                index = tc.get("index", 0)
                tc_id = tc.get("id", "")
                tc_name = tc.get("name", "")
                tc_args = tc.get("arguments", "")

                # Initialize tool call if new
                if index not in tool_calls_in_progress:
                    fc_id = tc_id or f"fc_{uuid.uuid4().hex[:16]}"
                    tool_calls_in_progress[index] = {
                        "id": fc_id,
                        "call_id": tc_id,
                        "name": tc_name,
                        "arguments": "",
                    }

                    yield encode_sse(
                        "response.output_item.added",
                        {
                            "type": "response.output_item.added",
                            "output_index": seq.next(),
                            "sequence_number": seq.next(),
                            "item": {
                                "id": fc_id,
                                "type": "function_call",
                                "call_id": tc_id,
                                "name": tc_name,
                                "arguments": "",
                                "status": "in_progress",
                            },
                        },
                    )

                # Update arguments
                if tc_args:
                    tool_calls_in_progress[index]["arguments"] += str(tc_args)
                    async for piece in iter_text_deltas(str(tc_args)):
                        yield encode_sse(
                            "response.function_call_arguments.delta",
                            {
                                "type": "response.function_call_arguments.delta",
                                "item_id": tool_calls_in_progress[index]["id"],
                                "output_index": index,
                                "delta": piece,
                                "sequence_number": seq.next(),
                            },
                        )

    merged_text = "".join(full_text_parts)

    # Emit completion events
    if tool_calls_in_progress:
        # Emit completion for each function call
        for index, tc_data in sorted(tool_calls_in_progress.items()):
            yield encode_sse(
                "response.function_call_arguments.done",
                {
                    "type": "response.function_call_arguments.done",
                    "item_id": tc_data["id"],
                    "output_index": index,
                    "name": tc_data["name"],
                    "arguments": tc_data["arguments"],
                    "sequence_number": seq.next(),
                },
            )
            yield encode_sse(
                "response.output_item.done",
                {
                    "type": "response.output_item.done",
                    "output_index": index,
                    "sequence_number": seq.next(),
                    "item": {
                        "id": tc_data["id"],
                        "type": "function_call",
                        "call_id": tc_data["call_id"],
                        "name": tc_data["name"],
                        "arguments": tc_data["arguments"],
                        "status": "completed",
                    },
                },
            )
    else:
        # Text response completion
        if current_output_index == 0 or full_text_parts:
            yield encode_sse(
                "response.output_text.done",
                {
                    "type": "response.output_text.done",
                    "item_id": msg_id,
                    "output_index": 0,
                    "content_index": 0,
                    "text": merged_text,
                    "logprobs": _LOGPROBS,
                    "sequence_number": seq.next(),
                },
            )
            yield encode_sse(
                "response.content_part.done",
                {
                    "type": "response.content_part.done",
                    "item_id": msg_id,
                    "output_index": 0,
                    "content_index": 0,
                    "sequence_number": seq.next(),
                    "part": {
                        "type": "output_text",
                        "text": merged_text,
                        "annotations": [],
                    },
                },
            )
            yield encode_sse(
                "response.output_item.done",
                {
                    "type": "response.output_item.done",
                    "output_index": 0,
                    "sequence_number": seq.next(),
                    "item": {
                        "id": msg_id,
                        "type": "message",
                        "status": "completed",
                        "role": role_detected or "assistant",
                        "content": [
                            {"type": "output_text", "text": merged_text, "annotations": []}
                        ],
                    },
                },
            )

    # Build final response
    cc = {"usage": usage_obj} if usage_obj else {}
    final = build_completed_response(
        resp_id=resp_id,
        msg_id=msg_id,
        model=displayed_model,
        req_body=req_body,
        assistant_text=merged_text,
        cc=cc,
    )
    yield encode_sse(
        "response.completed",
        {
            "type": "response.completed",
            "sequence_number": seq.next(),
            "response": final,
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
    """Convert a non-streaming completion into Responses SSE.

    For /v1/responses endpoints when stream=True is requested but
    the underlying API doesn't support streaming.
    """
    seq = SequenceGenerator()
    skel = response_skeleton(resp_id, displayed_model, req_body)

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

    # Extract content and tool calls
    choices = completion.get("choices") or []
    if choices:
        message = choices[0].get("message") or {}
        content = message.get("content", "")
        tool_calls = message.get("tool_calls", [])

        output_idx = 0

        if tool_calls:
            for tc in tool_calls:
                if not isinstance(tc, dict):
                    continue
                fn = tc.get("function", {})
                name = fn.get("name", "")
                args = fn.get("arguments", "")
                fc_id = tc.get("id", f"fc_{uuid.uuid4().hex[:16]}")
                call_id = tc.get("id", "")

                yield encode_sse(
                    "response.output_item.added",
                    {
                        "type": "response.output_item.added",
                        "output_index": output_idx,
                        "sequence_number": seq.next(),
                        "item": {
                            "id": fc_id,
                            "type": "function_call",
                            "call_id": call_id,
                            "name": name,
                            "arguments": "",
                            "status": "in_progress",
                        },
                    },
                )

                async for piece in iter_text_deltas(str(args)):
                    yield encode_sse(
                        "response.function_call_arguments.delta",
                        {
                            "type": "response.function_call_arguments.delta",
                            "item_id": fc_id,
                            "output_index": output_idx,
                            "delta": piece,
                            "sequence_number": seq.next(),
                        },
                    )

                yield encode_sse(
                    "response.function_call_arguments.done",
                    {
                        "type": "response.function_call_arguments.done",
                        "item_id": fc_id,
                        "output_index": output_idx,
                        "name": name,
                        "arguments": str(args),
                        "sequence_number": seq.next(),
                    },
                )

                yield encode_sse(
                    "response.output_item.done",
                    {
                        "type": "response.output_item.done",
                        "output_index": output_idx,
                        "sequence_number": seq.next(),
                        "item": {
                            "id": fc_id,
                            "type": "function_call",
                            "call_id": call_id,
                            "name": name,
                            "arguments": str(args),
                            "status": "completed",
                        },
                    },
                )
                output_idx += 1
        elif content:
            yield encode_sse(
                "response.output_item.added",
                {
                    "type": "response.output_item.added",
                    "output_index": 0,
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

            async for piece in iter_text_deltas(content):
                yield encode_sse(
                    "response.output_text.delta",
                    {
                        "type": "response.output_text.delta",
                        "item_id": msg_id,
                        "output_index": 0,
                        "content_index": 0,
                        "delta": piece,
                        "logprobs": _LOGPROBS,
                        "sequence_number": seq.next(),
                    },
                )

            yield encode_sse(
                "response.output_text.done",
                {
                    "type": "response.output_text.done",
                    "item_id": msg_id,
                    "output_index": 0,
                    "content_index": 0,
                    "text": content,
                    "logprobs": _LOGPROBS,
                    "sequence_number": seq.next(),
                },
            )

            yield encode_sse(
                "response.content_part.done",
                {
                    "type": "response.content_part.done",
                    "item_id": msg_id,
                    "output_index": 0,
                    "content_index": 0,
                    "sequence_number": seq.next(),
                    "part": {
                        "type": "output_text",
                        "text": content,
                        "annotations": [],
                    },
                },
            )

            yield encode_sse(
                "response.output_item.done",
                {
                    "type": "response.output_item.done",
                    "output_index": 0,
                    "sequence_number": seq.next(),
                    "item": {
                        "id": msg_id,
                        "type": "message",
                        "status": "completed",
                        "role": "assistant",
                        "content": [
                            {"type": "output_text", "text": content, "annotations": []}
                        ],
                    },
                },
            )

    final = build_completed_response(
        resp_id=resp_id,
        msg_id=msg_id,
        model=displayed_model,
        req_body=req_body,
        assistant_text=content if choices else "",
        cc=completion,
    )

    yield encode_sse(
        "response.completed",
        {
            "type": "response.completed",
            "sequence_number": seq.next(),
            "response": final,
        },
    )