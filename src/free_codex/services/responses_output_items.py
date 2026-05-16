"""Map Chat Completions assistant messages to OpenAI Responses `output` items."""

from __future__ import annotations

import uuid
from typing import Any


def new_fc_id() -> str:
    return f"fc_{uuid.uuid4().hex[:24]}"


def new_msg_id() -> str:
    return f"msg_{uuid.uuid4().hex[:24]}"


def new_call_id() -> str:
    return f"call_{uuid.uuid4().hex[:24]}"


def text_from_message_content(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") in ("text", "output_text", "input_text"):
                t = block.get("text")
                if isinstance(t, str):
                    parts.append(t)
        return "".join(parts)
    return ""


def message_to_response_output_items(message: dict[str, Any]) -> list[dict[str, Any]]:
    """Turn a chat/completions assistant `message` into Responses API `output` entries."""
    items: list[dict[str, Any]] = []

    body_text = text_from_message_content(message.get("content")).strip()
    if body_text:
        items.append(
            {
                "id": new_msg_id(),
                "type": "message",
                "status": "completed",
                "role": "assistant",
                "content": [
                    {
                        "type": "output_text",
                        "text": body_text,
                        "annotations": [],
                    }
                ],
            }
        )

    for tc in message.get("tool_calls") or []:
        if not isinstance(tc, dict):
            continue
        fn = tc.get("function")
        if not isinstance(fn, dict):
            continue
        name = fn.get("name")
        if not name:
            continue
        raw_args = fn.get("arguments")
        if raw_args is None:
            args = "{}"
        elif isinstance(raw_args, str):
            args = raw_args
        else:
            args = str(raw_args)

        call_id = tc.get("id") or new_call_id()
        items.append(
            {
                "type": "function_call",
                "id": new_fc_id(),
                "call_id": call_id,
                "name": str(name),
                "arguments": args,
                "status": "completed",
            }
        )

    return items


def output_from_chat_completion(cc: dict[str, Any]) -> list[dict[str, Any]]:
    choices = cc.get("choices") or []
    if not choices:
        return []
    msg = choices[0].get("message")
    if not isinstance(msg, dict):
        return []
    return message_to_response_output_items(msg)
