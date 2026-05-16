"""Enhanced payload normalization for OpenAI-compatible APIs with comprehensive tool support."""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

logger = logging.getLogger("free-codex.nim")


def normalize_chat_payload_for_nim(payload: dict[str, Any]) -> dict[str, Any]:
    """Fix Codex/Responses-style tools and tool_calls so NIM accepts the body.

    Handles:
    - OpenAI function calling format
    - Responses API tool format
    - Nested tool definitions
    - Invalid tool_call arguments
    """
    # Normalize messages including tool calls
    if "messages" in payload:
        normalized_messages = normalize_messages(payload["messages"])
        payload["messages"] = normalized_messages

    # Handle tools - supports multiple format variations
    raw_tools = payload.get("tools")
    if raw_tools:
        fixed_tools = normalize_tools_list(raw_tools)
        if fixed_tools:
            payload["tools"] = fixed_tools
        else:
            # Remove unsupported tools but don't fail
            payload.pop("tools", None)
            logger.warning("No valid tools found after normalization, removing from payload")
    elif "functions" in payload:
        # Legacy OpenAI functions format - convert to tools
        legacy_functions = payload.pop("functions", [])
        if legacy_functions:
            converted_tools = [
                {
                    "type": "function",
                    "function": {
                        "name": f.get("name", ""),
                        "description": f.get("description", ""),
                        "parameters": f.get("parameters", {"type": "object", "properties": {}}),
                    }
                }
                for f in legacy_functions
                if f.get("name")
            ]
            if converted_tools:
                payload["tools"] = converted_tools

    # Handle tool_choice
    if payload.get("tools"):
        if payload.get("tool_choice") is not None:
            payload["tool_choice"] = normalize_tool_choice(payload["tool_choice"])
    else:
        # No tools - ensure tool_choice is compatible
        tc = payload.get("tool_choice")
        if isinstance(tc, dict):
            # Force to "none" if tools were stripped
            payload["tool_choice"] = "none"
        elif tc not in (None, "none", "auto"):
            payload["tool_choice"] = "auto"

    # Ensure reasonable defaults for complex models
    if payload.get("max_tokens") is None or payload.get("max_tokens", 0) < 256:
        # Don't force max_tokens, let models use their defaults
        pass

    # Normalize temperature for models that need it
    if "temperature" not in payload:
        payload["temperature"] = 0.7  # Safe default

    return payload


def normalize_messages(messages: list[Any]) -> list[dict[str, Any]]:
    """Normalize all message formats."""
    out: list[dict[str, Any]] = []
    for m in messages:
        if not isinstance(m, dict):
            continue
        msg = normalize_single_message(m)
        if msg:
            out.append(msg)
    return out


def normalize_single_message(msg: dict[str, Any]) -> Optional[dict[str, Any]]:
    """Normalize a single message, handling tool calls and content."""
    if not isinstance(msg, dict):
        return None

    role = msg.get("role", "")
    if not role:
        return None

    result = {
        "role": role,
    }

    # Handle content - can be string, list, or None
    content = msg.get("content")
    if content is not None:
        if isinstance(content, str):
            result["content"] = content
        elif isinstance(content, list):
            # Handle content blocks (text, image_url, etc.)
            normalized_content = normalize_content_blocks(content)
            if normalized_content:
                result["content"] = normalized_content

    # Handle name (for function responses and multi-agent)
    if msg.get("name"):
        result["name"] = str(msg["name"])

    # Handle tool calls
    tcs = msg.get("tool_calls")
    if isinstance(tcs, list):
        fixed_calls = []
        for tc in tcs:
            norm = normalize_tool_call(tc)
            if norm:
                fixed_calls.append(norm)
        if fixed_calls:
            result["tool_calls"] = fixed_calls
    elif tcs:
        # Single tool_call object (not in list)
        norm = normalize_tool_call(tcs)
        if norm:
            result["tool_calls"] = [norm]

    # Handle tool responses
    if role == "tool":
        if msg.get("tool_call_id"):
            result["tool_call_id"] = str(msg["tool_call_id"])
        if msg.get("name"):
            result["name"] = str(msg["name"])
        # Tool response content should be string
        if content:
            result["content"] = str(content) if not isinstance(content, str) else content

    # Handle function_call (legacy format)
    if msg.get("function_call"):
        fc = msg["function_call"]
        if isinstance(fc, dict) and fc.get("name"):
            # Convert to tool_call format
            call_id = msg.get("tool_call_id", f"call_{id(fc)}")
            result["tool_call_id"] = call_id
            if "tool_calls" not in result:
                result["tool_calls"] = [{
                    "id": call_id,
                    "type": "function",
                    "function": {
                        "name": str(fc["name"]),
                        "arguments": arguments_to_string(fc.get("arguments")),
                    }
                }]

    return result


def normalize_content_blocks(content: list) -> Optional[Union[str, list]]:
    """Normalize content blocks into NIM-compatible format."""
    if not content:
        return None

    result_blocks = []
    has_text = False
    text_parts = []

    for block in content:
        if not isinstance(block, dict):
            continue

        btype = block.get("type", "")

        if btype == "text":
            text = block.get("text", "")
            if text:
                text_parts.append(text)
                has_text = True
        elif btype == "image_url":
            # Convert to simple format NIM can understand
            image_url = block.get("image_url", {})
            if isinstance(image_url, dict):
                url = image_url.get("url", "")
                if url:
                    result_blocks.append({
                        "type": "image_url",
                        "image_url": {"url": url}
                    })
        elif btype == "input_image":
            # Another common format
            image_data = block.get("image_bytes") or block.get("url") or block.get("image_url")
            if image_data:
                result_blocks.append({
                    "type": "image_url",
                    "image_url": {"url": image_data}
                })

    # If we only have text blocks, return simple string
    if result_blocks:
        if has_text and text_parts:
            result_blocks.insert(0, {"type": "text", "text": "\n".join(text_parts)})
        return result_blocks
    elif text_parts:
        return "\n".join(text_parts)

    return None


def normalize_tool_call(tc: Any) -> Optional[dict[str, Any]]:
    """Normalize a tool call to standard format."""
    if not isinstance(tc, dict):
        return None

    # Primary format: { function: { name, arguments } }
    if isinstance(tc.get("function"), dict) and tc["function"].get("name"):
        fn = tc["function"]
        return {
            "id": str(tc.get("id", f"call_{id(tc)}")),
            "type": "function",
            "function": {
                "name": str(fn["name"]),
                "arguments": arguments_to_string(fn.get("arguments")),
            },
        }

    # Alternate format: flat with name
    if tc.get("type") == "function" and tc.get("name"):
        return {
            "id": str(tc.get("id", f"call_{id(tc)}")),
            "type": "function",
            "function": {
                "name": str(tc["name"]),
                "arguments": arguments_to_string(tc.get("arguments")),
            },
        }

    # Nested function object format
    if tc.get("type") == "function" and isinstance(tc.get("function"), dict):
        fn = tc["function"]
        return {
            "id": str(tc.get("id", f"call_{id(tc)}")),
            "type": "function",
            "function": {
                "name": str(fn.get("name", "")),
                "arguments": arguments_to_string(fn.get("arguments")),
            },
        }

    return None


def arguments_to_string(args: Any) -> str:
    """Convert arguments to JSON string, handling edge cases."""
    if args is None:
        return "{}"
    if isinstance(args, str):
        # Validate it's valid JSON
        try:
            json.loads(args)
            return args
        except json.JSONDecodeError:
            # Try to fix common issues
            return args.strip()
    if isinstance(args, dict):
        try:
            return json.dumps(args)
        except (TypeError, ValueError):
            return "{}"
    if isinstance(args, list):
        try:
            return json.dumps(args)
        except (TypeError, ValueError):
            return "[]"

    # Last resort - try string conversion
    try:
        return json.dumps({"value": str(args)})
    except Exception:
        return "{}"


def normalize_tools_list(tools: list[Any]) -> list[dict[str, Any]]:
    """Normalize list of tools to standard format."""
    out: list[dict[str, Any]] = []
    for raw in tools:
        item = normalize_one_tool(raw)
        if item:
            out.append(item)
    return out


def normalize_one_tool(raw: Any) -> Optional[dict[str, Any]]:
    """Normalize a single tool definition."""
    if not isinstance(raw, dict):
        return None

    ttype = raw.get("type", "")

    # Format 1: Chat Completions { type: "function", function: { name, description, parameters } }
    if ttype == "function" and isinstance(raw.get("function"), dict):
        fn = raw["function"]
        if not fn.get("name"):
            return None
        return {
            "type": "function",
            "function": {
                "name": str(fn["name"]),
                "description": str(fn.get("description") or ""),
                "parameters": normalize_parameters(fn.get("parameters")),
            },
        }

    # Format 2: Responses/Codex flat { type: "function", name, description, parameters }
    if ttype == "function" and raw.get("name"):
        return {
            "type": "function",
            "function": {
                "name": str(raw["name"]),
                "description": str(raw.get("description", "")),
                "parameters": normalize_parameters(raw.get("parameters")),
            },
        }

    # Format 3: Legacy { name, description, parameters } (no type)
    if raw.get("name") and not ttype:
        return {
            "type": "function",
            "function": {
                "name": str(raw["name"]),
                "description": str(raw.get("description", "")),
                "parameters": normalize_parameters(raw.get("parameters")),
            },
        }

    # Unsupported tool types (file_search, web_search, etc.)
    logger.debug(f"Skipping unsupported tool type: {ttype}")
    return None


def normalize_parameters(params: Any) -> dict[str, Any]:
    """Normalize tool parameters to JSON Schema format."""
    if params is None:
        return {"type": "object", "properties": {}}

    if not isinstance(params, dict):
        return {"type": "object", "properties": {}}

    # Ensure required structure
    result = {
        "type": params.get("type", "object"),
        "properties": params.get("properties", {}),
    }

    if params.get("required"):
        result["required"] = params["required"]

    # Validate properties are properly formatted
    if not isinstance(result["properties"], dict):
        result["properties"] = {}

    return result


def normalize_tool_choice(tool_choice: Any) -> Any:
    """Normalize tool_choice parameter."""
    # Valid string values
    if tool_choice in ("none", "auto", "required"):
        return tool_choice

    # Dictionary format
    if isinstance(tool_choice, dict):
        # Already in correct format
        if tool_choice.get("type") == "function":
            fn = tool_choice.get("function", {})
            if isinstance(fn, dict) and fn.get("name"):
                return tool_choice
        # Flat format with just name
        if "name" in tool_choice:
            return {
                "type": "function",
                "function": {"name": str(tool_choice["name"])},
            }

    # Invalid - return auto
    return "auto"


from typing import Union