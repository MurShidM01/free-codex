"""Resolve workspace root from Codex metadata / headers / env."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import Request


def workspace_root_from_request(body: dict[str, Any], request: Request) -> Path | None:
    meta = body.get("metadata")
    if isinstance(meta, dict):
        for key in ("workspace_root", "cwd", "working_directory"):
            raw = meta.get(key)
            if isinstance(raw, str) and raw.strip():
                return _safe_root(Path(raw.strip()))

    hdr = request.headers.get("x-free-codex-workspace") or request.headers.get(
        "X-Free-Codex-Workspace"
    )
    if isinstance(hdr, str) and hdr.strip():
        return _safe_root(Path(hdr.strip()))

    env_root = os.getenv("FREE_CODEX_WORKSPACE_ROOT", "").strip()
    if env_root:
        return _safe_root(Path(env_root))

    return None


def _safe_root(p: Path) -> Path | None:
    try:
        resolved = p.expanduser().resolve(strict=False)
    except OSError:
        return None
    if not resolved.exists() or not resolved.is_dir():
        return None
    return resolved
