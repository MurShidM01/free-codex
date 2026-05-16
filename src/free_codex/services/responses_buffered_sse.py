"""Turn a non-streaming NIM completion into Responses SSE Codex accepts (ordered events + sequence_number)."""

from __future__ import annotations

from typing import Any, AsyncGenerator

from .responses_bridge import (
    build_completed_response,
    chat_completion_assistant_content,
    response_skeleton,
)
from .responses_output_items import output_from_chat_completion
from .responses_sse_codec import encode_sse
from .responses_sse_chunks import iter_text_deltas

_LOGPROBS: list[dict[str, Any]] = []


class _Seq:
    __slots__ = ("_n",)

    def __init__(self) -> None:
        self._n = 0

    def next(self) -> int:
        n = self._n
        self._n += 1
        return n


def _message_item_text(item: dict[str, Any]) -> str:
    parts: list[str] = []
    for block in item.get("content") or []:
        if isinstance(block, dict) and block.get("type") == "output_text":
            t = block.get("text")
            if isinstance(t, str):
                parts.append(t)
    return "".join(parts)


async def _emit_assistant_message_sse(
    *,
    msg_id: str,
    output_index: int,
    text: str,
    seq: _Seq,
) -> AsyncGenerator[bytes, None]:
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
    for piece in iter_text_deltas(text):
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
    iid = str(item.get("id") or "")
    name = str(item.get("name") or "")
    args = str(item.get("arguments") or "{}")
    call_id = str(item.get("call_id") or "")
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
    for piece in iter_text_deltas(args):
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
    seq = _Seq()
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

    out = output_from_chat_completion(completion)
    if not out:
        text = chat_completion_assistant_content(completion)
        final = build_completed_response(
            resp_id=resp_id,
            msg_id=msg_id,
            model=displayed_model,
            req_body=req_body,
            assistant_text=text,
            cc=completion,
            output=None,
        )
        async for chunk in _emit_assistant_message_sse(
            msg_id=msg_id, output_index=0, text=text, seq=seq
        ):
            yield chunk
    else:
        final = build_completed_response(
            resp_id=resp_id,
            msg_id=msg_id,
            model=displayed_model,
            req_body=req_body,
            assistant_text="",
            cc=completion,
            output=out,
        )
        idx = 0
        for item in out:
            typ = item.get("type")
            if typ == "message":
                mid = str(item.get("id") or msg_id)
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

    yield encode_sse(
        "response.completed",
        {
            "type": "response.completed",
            "sequence_number": seq.next(),
            "response": final,
        },
    )
