"""Responses API tool calls / tool outputs → Chat Completions messages."""

from __future__ import annotations

import json
from typing import Any


def format_tool_output_body(output: Any) -> str:
    if output is None:
        return ""
    if isinstance(output, str):
        return output
    if isinstance(output, list):
        parts: list[str] = []
        for el in output:
            if isinstance(el, dict):
                t = el.get("text")
                if isinstance(t, str):
                    parts.append(t)
                    continue
                if el.get("type") in ("stdout", "stderr"):
                    chunk = el.get("text") or el.get("data")
                    if isinstance(chunk, str):
                        parts.append(chunk)
                        continue
                # Handle computer_call_output and function_call_output blocks
                if el.get("type") in ("computer_call_output", "function_call_output"):
                    output_text = el.get("output", el.get("text", ""))
                    if isinstance(output_text, str):
                        parts.append(output_text)
                        continue
                    parts.append(json.dumps(output_text, separators=(",", ":"), ensure_ascii=False))
                    continue
                parts.append(json.dumps(el, separators=(",", ":"), ensure_ascii=False))
            else:
                parts.append(str(el))
        return "\n".join(parts)
    if isinstance(output, dict):
        # Handle dict outputs (e.g., file contents, directory listings)
        output_text = output.get("text") or output.get("output") or output.get("content", "")
        if isinstance(output_text, str):
            return output_text
        # Try to extract meaningful content from dict
        if "stdout" in output:
            return str(output["stdout"])
        if "result" in output:
            return str(output["result"])
        return json.dumps(output, separators=(",", ":"), ensure_ascii=False)
    return json.dumps(output, separators=(",", ":"), ensure_ascii=False)


def chat_tool_call_from_response_function_call(item: dict[str, Any]) -> dict[str, Any] | None:
    if item.get("type") != "function_call":
        return None
    call_id = item.get("call_id")
    name = item.get("name")
    if not call_id or not name:
        return None
    raw = item.get("arguments")
    if isinstance(raw, str):
        args = raw
    elif raw is None:
        args = "{}"
    else:
        args = json.dumps(raw, separators=(",", ":"), ensure_ascii=False)
    return {
        "id": str(call_id),
        "type": "function",
        "function": {"name": str(name), "arguments": args},
    }


def tool_output_to_chat_message(item: dict[str, Any]) -> dict[str, Any] | None:
    t = item.get("type")
    if t == "function_call_output":
        cid = item.get("call_id")
        if not cid:
            return None
        return {
            "role": "tool",
            "tool_call_id": str(cid),
            "content": format_tool_output_body(item.get("output")),
        }
    if t == "custom_tool_call_output":
        cid = item.get("call_id")
        if not cid:
            return None
        return {
            "role": "tool",
            "tool_call_id": str(cid),
            "content": format_tool_output_body(item.get("output")),
        }
    if t == "local_shell_call_output":
        cid = item.get("id") or item.get("call_id")
        if not cid:
            return None
        raw = item.get("output")
        body = raw if isinstance(raw, str) else format_tool_output_body(raw)
        return {"role": "tool", "tool_call_id": str(cid), "content": body}
    if t == "shell_call_output":
        cid = item.get("call_id")
        if not cid:
            return None
        return {
            "role": "tool",
            "tool_call_id": str(cid),
            "content": format_tool_output_body(item.get("output")),
        }
    if t == "apply_patch_call_output":
        cid = item.get("call_id")
        if not cid:
            return None
        payload = {"status": item.get("status"), "output": item.get("output")}
        return {
            "role": "tool",
            "tool_call_id": str(cid),
            "content": json.dumps(payload, separators=(",", ":"), ensure_ascii=False),
        }
    if t == "computer_call_output":
        cid = item.get("call_id")
        if not cid:
            return None
        # Extract output from various possible fields
        output = item.get("output") or item.get("result") or item.get("text") or ""
        return {
            "role": "tool",
            "tool_call_id": str(cid),
            "content": format_tool_output_body(output),
        }
    # Handle generic output types that might have call_id
    if t and "call_id" in item:
        cid = item.get("call_id")
        output = item.get("output") or item.get("result") or item.get("text", "")
        if cid and output:
            return {
                "role": "tool",
                "tool_call_id": str(cid),
                "content": format_tool_output_body(output),
            }
    return None
