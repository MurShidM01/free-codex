"""Normalize chat/completions JSON for strict NVIDIA NIM OpenAI-compatible parsers."""

from __future__ import annotations

import json
from typing import Any


def normalize_chat_payload_for_nim(payload: dict[str, Any]) -> dict[str, Any]:
    """Fix Codex/Responses-style tools and tool_calls so NIM accepts the body."""
    if "messages" in payload:
        payload["messages"] = normalize_messages(payload["messages"])

    raw_tools = payload.get("tools")
    if raw_tools:
        fixed_tools = normalize_tools_list(raw_tools)
        if fixed_tools:
            payload["tools"] = fixed_tools
        else:
            payload.pop("tools", None)
    elif "tools" in payload:
        payload.pop("tools", None)

    if payload.get("tools"):
        if payload.get("tool_choice") is not None:
            payload["tool_choice"] = normalize_tool_choice(payload["tool_choice"])
    else:
        tc = payload.get("tool_choice")
        if isinstance(tc, dict):
            payload["tool_choice"] = "none"
        elif tc not in (None, "none", "auto"):
            payload["tool_choice"] = "auto"

    return payload


def normalize_messages(messages: list[Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for m in messages:
        if not isinstance(m, dict):
            continue
        msg = dict(m)
        tcs = msg.get("tool_calls")
        if isinstance(tcs, list):
            fixed_calls: list[dict[str, Any]] = []
            for tc in tcs:
                if not tc:
                    continue
                norm = normalize_tool_call(tc)
                if norm.get("type") == "function" and norm.get("function", {}).get("name"):
                    fixed_calls.append(norm)
            if fixed_calls:
                msg["tool_calls"] = fixed_calls
            else:
                msg.pop("tool_calls", None)
        out.append(msg)
    return out


def normalize_tool_call(tc: Any) -> dict[str, Any]:
    if not isinstance(tc, dict):
        return {}
    if isinstance(tc.get("function"), dict) and tc["function"].get("name"):
        fn = tc["function"]
        return {
            "id": str(tc.get("id", "")),
            "type": "function",
            "function": {
                "name": str(fn["name"]),
                "arguments": arguments_to_string(fn.get("arguments")),
            },
        }
    if tc.get("type") == "function" and tc.get("name"):
        return {
            "id": str(tc.get("id", "")),
            "type": "function",
            "function": {
                "name": str(tc["name"]),
                "arguments": arguments_to_string(tc.get("arguments")),
            },
        }
    return tc


def arguments_to_string(args: Any) -> str:
    if args is None:
        return "{}"
    if isinstance(args, str):
        return args
    try:
        return json.dumps(args)
    except (TypeError, ValueError):
        return "{}"


def normalize_tools_list(tools: list[Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for raw in tools:
        item = normalize_one_tool(raw)
        if item:
            out.append(item)
    return out


def normalize_one_tool(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None

    ttype = raw.get("type")

    # Chat Completions shape already
    if ttype == "function" and isinstance(raw.get("function"), dict):
        fn = raw["function"]
        if not fn.get("name"):
            return None
        return {
            "type": "function",
            "function": {
                "name": str(fn["name"]),
                "description": str(fn.get("description") or ""),
                "parameters": fn.get("parameters")
                or {"type": "object", "properties": {}},
            },
        }

    # Responses / Codex flat shape: { type, name, description, parameters }
    if ttype == "function" and raw.get("name"):
        return {
            "type": "function",
            "function": {
                "name": str(raw["name"]),
                "description": str(raw.get("description") or ""),
                "parameters": raw.get("parameters")
                or {"type": "object", "properties": {}},
            },
        }

    # Unsupported for NIM chat completions (file_search, web_search, etc.)
    return None


def normalize_tool_choice(tool_choice: Any) -> Any:
    if tool_choice in ("none", "auto", "required"):
        return tool_choice
    if not isinstance(tool_choice, dict):
        return tool_choice
    if tool_choice.get("type") == "function":
        fn = tool_choice.get("function")
        if isinstance(fn, dict) and fn.get("name"):
            return tool_choice
        if "name" in tool_choice:
            return {
                "type": "function",
                "function": {"name": str(tool_choice["name"])},
            }
    return tool_choice
