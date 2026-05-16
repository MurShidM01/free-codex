"""Shallow workspace listing + small-file excerpts for model context."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Iterable


def list_workspace_entries(root: Path, *, limit: int = 400) -> list[str]:
    names: list[str] = []
    try:
        for entry in sorted(root.iterdir(), key=lambda p: p.name.lower()):
            if entry.name.startswith("."):
                continue
            suffix = "/" if entry.is_dir() else ""
            names.append(f"{entry.name}{suffix}")
            if len(names) >= limit:
                break
    except OSError:
        return []
    return names


def collect_recent_user_text(messages: list[dict[str, object]]) -> str:
    parts: list[str] = []
    for msg in reversed(messages[-12:]):
        if msg.get("role") != "user":
            continue
        c = msg.get("content")
        if isinstance(c, str):
            parts.append(c)
        elif isinstance(c, list):
            for block in c:
                if isinstance(block, dict) and isinstance(block.get("text"), str):
                    parts.append(block["text"])
        if parts:
            break
    return "\n".join(parts)


def guess_named_paths(text: str, listing: Iterable[str]) -> list[str]:
    listing_set = set(listing)
    hits: list[str] = []
    seen: set[str] = set()

    for word in re.findall(r"[\w\-./\\]+\.[\w]{1,12}", text):
        base = Path(word.replace("\\", "/")).name
        if base in listing_set and base not in seen:
            hits.append(base)
            seen.add(base)

    for m in re.finditer(
        r"\b[A-Za-z0-9_.\-]+\.(?:py|toml|md|txt|json|yaml|yml|tsx|ts|js)\b", text
    ):
        name = m.group(0)
        if name in listing_set and name not in seen:
            hits.append(name)
            seen.add(name)

    for line in listing_set:
        if "/" in line or line.endswith("/"):
            continue
        if len(line) < 3:
            continue
        if line in text and line not in seen:
            hits.append(line)
            seen.add(line)
            if len(hits) >= 24:
                break

    return hits[:16]


def read_snippets(root: Path, filenames: list[str]) -> list[tuple[str, str]]:
    max_bytes = int(os.getenv("FREE_CODEX_WORKSPACE_SNIPPET_BYTES", "49152"))
    max_lines = int(os.getenv("FREE_CODEX_WORKSPACE_SNIPPET_LINES", "160"))
    out: list[tuple[str, str]] = []
    for name in filenames:
        path = (root / name).resolve()
        try:
            path.relative_to(root.resolve())
        except ValueError:
            continue
        if not path.is_file():
            continue
        try:
            raw = path.read_bytes()
        except OSError:
            continue
        if len(raw) > max_bytes:
            raw = raw[:max_bytes]
        try:
            text = raw.decode("utf-8", errors="replace")
        except Exception:
            continue
        lines = text.splitlines()
        if len(lines) > max_lines:
            text = "\n".join(lines[:max_lines]) + "\n… [truncated]"
        out.append((name, text))
    return out


def format_workspace_block(
    root: Path,
    listing: list[str],
    snippets: list[tuple[str, str]],
) -> str:
    lines = [
        "[free-codex workspace assist]",
        f"Root: {root}",
        "Entries (non-hidden, shallow):",
    ]
    lines.extend(f"- {n}" for n in listing[:200])
    if snippets:
        lines.append("")
        lines.append("Referenced / matched files (truncated):")
        for fname, body in snippets:
            lines.append(f"--- {fname} ---")
            lines.append(body.rstrip())
            lines.append("")
    lines.append("[end workspace assist]")
    return "\n".join(lines).strip()
