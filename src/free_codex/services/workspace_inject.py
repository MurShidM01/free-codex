"""Inject optional workspace listing + snippets into chat messages."""

from __future__ import annotations

import os
from typing import Any

from fastapi import Request

from .workspace_resolve import workspace_root_from_request
from .workspace_scan import (
    collect_recent_user_text,
    format_workspace_block,
    guess_named_paths,
    list_workspace_entries,
    read_snippets,
)


def maybe_inject_workspace_context(
    messages: list[dict[str, Any]],
    body: dict[str, Any],
    request: Request,
) -> list[dict[str, Any]]:
    if os.getenv("FREE_CODEX_WORKSPACE_CONTEXT", "").strip() != "1":
        return messages

    root = workspace_root_from_request(body, request)
    if root is None:
        return messages

    listing = list_workspace_entries(root)
    if not listing:
        return messages

    user_blob = collect_recent_user_text(messages)
    picks = guess_named_paths(user_blob + "\n" + str(body.get("instructions") or ""), listing)
    snippets = read_snippets(root, picks)
    block = format_workspace_block(root, listing, snippets)

    for msg in messages:
        if msg.get("role") == "system":
            base = msg.get("content")
            if isinstance(base, str):
                msg["content"] = (base + "\n\n" + block).strip()
            else:
                msg["content"] = block
            return messages

    messages.insert(0, {"role": "system", "content": block})
    return messages
