"""Translate between OpenAI Responses API and Chat Completions (NIM)."""

from __future__ import annotations

import time
import uuid
from typing import Any


def make_ids() -> tuple[str, str]:
    suffix = uuid.uuid4().hex[:24]
    return f"resp_{suffix}", f"msg_{suffix}"


def usage_from_completion(u: dict[str, Any] | None) -> dict[str, Any] | None:
    if not u:
        return None
    inp = int(u.get("prompt_tokens") or 0)
    out = int(u.get("completion_tokens") or 0)
    total = int(u.get("total_tokens") or inp + out)
    details = u.get("output_tokens_details") if isinstance(u.get("output_tokens_details"), dict) else {}
    reasoning = int(details.get("reasoning_tokens") or 0)
    return {
        "input_tokens": inp,
        "input_tokens_details": {"cached_tokens": int(u.get("cached_tokens") or 0)},
        "output_tokens": out,
        "output_tokens_details": {"reasoning_tokens": reasoning},
        "total_tokens": total,
    }


def chat_completion_assistant_content(cc: dict[str, Any]) -> str:
    choices = cc.get("choices") or []
    if not choices:
        return ""
    msg = choices[0].get("message") or {}
    c = msg.get("content")
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        chunks: list[str] = []
        for part in c:
            if isinstance(part, dict) and isinstance(part.get("text"), str):
                chunks.append(part["text"])
        return "".join(chunks)
    return ""


def chat_payload_from_responses_request(
    body: dict[str, Any],
    messages: list[dict[str, Any]],
    slug_model: str,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": slug_model,
        "messages": messages,
        "stream": bool(body.get("stream")),
    }

    mirror = (
        "temperature",
        "top_p",
        "frequency_penalty",
        "presence_penalty",
        "stop",
        "user",
        "tools",
        "tool_choice",
        "response_format",
    )
    for k in mirror:
        if k in body and body[k] is not None:
            payload[k] = body[k]

    if body.get("max_output_tokens") is not None:
        payload["max_tokens"] = body["max_output_tokens"]
    if body.get("max_tokens") is not None:
        payload["max_tokens"] = body["max_tokens"]

    return payload


def response_skeleton(
    resp_id: str, displayed_model: str, req_body: dict[str, Any]
) -> dict[str, Any]:
    now = int(time.time())
    return {
        "id": resp_id,
        "object": "response",
        "created_at": now,
        "status": "in_progress",
        "error": None,
        "incomplete_details": None,
        "instructions": req_body.get("instructions"),
        "max_output_tokens": req_body.get("max_output_tokens"),
        "model": displayed_model,
        "output": [],
        "parallel_tool_calls": True,
        "previous_response_id": None,
        "reasoning": {"effort": None, "summary": None},
        "store": req_body.get("store", True),
        "temperature": req_body.get("temperature", 1.0),
        "text": {"format": {"type": "text"}},
        "tool_choice": req_body.get("tool_choice") or "auto",
        "tools": req_body.get("tools") or [],
        "top_p": req_body.get("top_p", 1.0),
        "truncation": "disabled",
        "usage": None,
        "user": req_body.get("user"),
        "metadata": req_body.get("metadata") or {},
    }


def build_completed_response(
    *,
    resp_id: str,
    msg_id: str,
    model: str,
    req_body: dict[str, Any],
    assistant_text: str,
    cc: dict[str, Any],
    output: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    now = int(time.time())
    if output is None:
        output = [
            {
                "id": msg_id,
                "type": "message",
                "status": "completed",
                "role": "assistant",
                "content": [
                    {
                        "type": "output_text",
                        "text": assistant_text,
                        "annotations": [],
                    }
                ],
            }
        ]
    return {
        "id": resp_id,
        "object": "response",
        "created_at": now,
        "status": "completed",
        "completed_at": now,
        "error": None,
        "incomplete_details": None,
        "instructions": req_body.get("instructions"),
        "max_output_tokens": req_body.get("max_output_tokens"),
        "model": model,
        "output": output,
        "parallel_tool_calls": True,
        "previous_response_id": None,
        "reasoning": {"effort": None, "summary": None},
        "store": req_body.get("store", True),
        "temperature": req_body.get("temperature", 1.0),
        "text": {"format": {"type": "text"}},
        "tool_choice": req_body.get("tool_choice") or "auto",
        "tools": req_body.get("tools") or [],
        "top_p": req_body.get("top_p", 1.0),
        "truncation": "disabled",
        "usage": usage_from_completion(cc.get("usage")),
        "user": req_body.get("user"),
        "metadata": req_body.get("metadata") or {},
    }

