"""Map OpenAI Responses API request bodies to Chat Completions messages."""

from __future__ import annotations

from typing import Any


def responses_body_to_chat_messages(
    body: dict[str, Any],
) -> tuple[list[dict[str, Any]], str]:
    """Return (messages, requested_model_slug)."""
    model = (body.get("model") or "").strip() or "nvidia_nim"

    msgs: list[dict[str, Any]] = []

    instructions = body.get("instructions")
    if isinstance(instructions, str) and instructions.strip():
        msgs.append({"role": "system", "content": instructions.strip()})

    inp = body.get("input")
    msgs.extend(normalize_input_messages(inp))

    return msgs, model


def normalize_input_messages(inp: Any) -> list[dict[str, Any]]:
    if inp is None:
        return [{"role": "user", "content": ""}]
    if isinstance(inp, str):
        return [{"role": "user", "content": inp}]
    if isinstance(inp, list):
        return messages_from_items(inp)
    return [{"role": "user", "content": str(inp)}]


def messages_from_items(items: list[Any]) -> list[dict[str, Any]]:
    from .responses_input_expand import response_items_to_chat_messages

    return response_items_to_chat_messages(items)


def normalize_one_item(item: dict[str, Any]) -> dict[str, Any] | None:
    role = item.get("role") or "user"
    ctype = item.get("type")

    if ctype == "input_text":
        txt = item.get("text") or ""
        return {"role": role, "content": txt}

    raw_content = item.get("content")

    if isinstance(raw_content, str):
        return {"role": role, "content": raw_content}

    if isinstance(raw_content, list):
        return {"role": role, "content": flatten_parts(raw_content, role)}

    if raw_content is not None:
        return {"role": role, "content": str(raw_content)}

    embed = item.get("tool_calls")
    if role == "assistant" and isinstance(embed, list) and embed:
        return {"role": "assistant", "content": None}
    return None


def flatten_parts(parts: list[Any], role_for_media: str) -> str:
    texts: list[str] = []
    for p in parts:
        if not isinstance(p, dict):
            texts.append(str(p))
            continue
        pt = p.get("type")
        if pt in ("input_text", "output_text", "text"):
            texts.append(p.get("text") or "")
        elif pt in ("input_image", "input_file"):
            texts.append("")  # NIM shim: skip binary / URL references
        elif pt == "reasoning":
            texts.append("")  # drop reasoning blocks from NIM payloads
        else:
            # Unknown structure (e.g. future Codex item types): best-effort
            texts.append(str(p))
    merged = "".join(part for part in texts if part)
    if merged:
        return merged
    if role_for_media == "assistant":
        return ""
    return "[unsupported input item omitted by free-codex proxy]"
