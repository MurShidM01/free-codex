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

    if ctype in ("input_image", "image_url"):
        source = item.get("image_url") or item.get("url") or item.get("image_bytes")
        if isinstance(source, dict):
            source = source.get("url")
        if source:
            return {"role": role, "content": [{"type": "image_url", "image_url": {"url": source}}]}

    if ctype in ("input_video", "video_url"):
        source = item.get("video_url") or item.get("url") or item.get("video_bytes")
        if isinstance(source, dict):
            source = source.get("url")
        if source:
            return {"role": role, "content": [{"type": "video_url", "video_url": {"url": source}}]}

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


def flatten_parts(parts: list[Any], role_for_media: str) -> Any:
    """Preserve supported multimodal blocks for the selected provider.

    Older NIM-only code flattened images into a placeholder before routing. That
    made it impossible for a capable provider (including a configured Puter
    model) to receive an image. The provider router now rejects unsupported
    media explicitly and the provider-specific normalizer decides its native
    shape.
    """
    texts: list[str] = []
    blocks: list[dict[str, Any]] = []
    for p in parts:
        if not isinstance(p, dict):
            texts.append(str(p))
            continue
        pt = p.get("type")
        if pt in ("input_text", "output_text", "text"):
            text = p.get("text") or ""
            if text:
                texts.append(str(text))
        elif pt in ("input_image", "image_url"):
            source = p.get("image_url") or p.get("url") or p.get("image_bytes")
            if isinstance(source, dict):
                source = source.get("url")
            if source:
                blocks.append({"type": "image_url", "image_url": {"url": source}})
        elif pt in ("input_video", "video_url"):
            source = p.get("video_url") or p.get("url") or p.get("video_bytes")
            if isinstance(source, dict):
                source = source.get("url")
            if source:
                blocks.append({"type": "video_url", "video_url": {"url": source}})
        elif pt == "input_file":
            # File references stay visible to provider capability validation;
            # text-only transports will return an explicit unsupported error.
            source = p.get("file_url") or p.get("url") or p.get("file_id")
            if source:
                blocks.append({"type": "input_file", "file_url": source})
        elif pt == "reasoning":
            # Reasoning is model output, never silently replay it as input.
            continue
        else:
            texts.append(str(p))
    merged = "".join(part for part in texts if part)
    if not blocks:
        if merged:
            return merged
        return "" if role_for_media == "assistant" else "[unsupported input item omitted by free-codex proxy]"
    content: list[dict[str, Any]] = []
    if merged:
        content.append({"type": "text", "text": merged})
    content.extend(blocks)
    return content
