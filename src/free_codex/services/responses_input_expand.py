"""Expand Responses `input[]` into Chat Completions messages (tool I/O + call batching)."""

from __future__ import annotations

import json
import uuid
from typing import Any

from .nim_chat_payload import normalize_tool_call
from .responses_tool_io import (
    chat_tool_call_from_response_function_call,
    tool_output_to_chat_message,
)


def response_items_to_chat_messages(items: list[Any]) -> list[dict[str, Any]]:
    """Codex sends tool results as typed items; map them to role=tool messages NIM understands."""
    out: list[dict[str, Any]] = []
    pending_text: list[str] = []
    pending_calls: list[dict[str, Any]] = []

    def flush_assistant() -> None:
        nonlocal pending_text, pending_calls
        if not pending_text and not pending_calls:
            return
        merged = "".join(pending_text).strip()
        msg: dict[str, Any] = {"role": "assistant"}
        if merged:
            msg["content"] = merged
        elif pending_calls:
            msg["content"] = None
        else:
            msg["content"] = ""
        if pending_calls:
            msg["tool_calls"] = pending_calls[:]
        pending_text = []
        pending_calls = []
        out.append(msg)

    for raw in items:
        if not isinstance(raw, dict):
            continue

        tool_msg = tool_output_to_chat_message(raw)
        if tool_msg:
            flush_assistant()
            out.append(tool_msg)
            continue

        # Handle computer_call type (Claude computer use)
        if raw.get("type") == "computer_call":
            cc = raw.get("call")
            if isinstance(cc, dict):
                cid = cc.get("id") or f"call_{uuid.uuid4().hex[:16]}"
                fn = cc.get("function")
                if isinstance(fn, dict):
                    name = fn.get("name", "")
                    args = fn.get("arguments", "{}")
                    if isinstance(args, str):
                        args_str = args
                    else:
                        args_str = json.dumps(args)
                    pending_calls.append({
                        "id": cid,
                        "type": "function",
                        "function": {"name": name, "arguments": args_str}
                    })
            continue

        if raw.get("type") == "function_call":
            tc = chat_tool_call_from_response_function_call(raw)
            if tc:
                pending_calls.append(tc)
            continue

        # Handle input_audio (audio input - skip)
        if raw.get("type") == "input_audio":
            continue

        flush_assistant()

        parsed = _normalize_message_like_item(raw)
        if not parsed:
            continue

        role = parsed.get("role") or "user"
        if role == "developer":
            parsed = dict(parsed)
            parsed["role"] = "system"

        if parsed.get("role") == "assistant":
            body = parsed.get("content")
            if isinstance(body, str) and body:
                pending_text.append(body)
            elif isinstance(body, str):
                pass
            elif body is not None:
                out.append(parsed)

            embed = raw.get("tool_calls")
            if isinstance(embed, list):
                for tc in embed:
                    norm = normalize_tool_call(tc)
                    fn = norm.get("function") if isinstance(norm, dict) else None
                    if (
                        isinstance(fn, dict)
                        and norm.get("type") == "function"
                        and fn.get("name")
                    ):
                        pending_calls.append(norm)
            continue

        out.append(parsed)

    flush_assistant()
    return out if out else [{"role": "user", "content": ""}]


def _normalize_message_like_item(item: dict[str, Any]) -> dict[str, Any] | None:
    from .responses_messages import normalize_one_item

    return normalize_one_item(item)
