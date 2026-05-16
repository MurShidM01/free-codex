"""Browser admin UI + APIs for Free Codex .env."""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field

from ..services.admin_env import (
    env_api_payload,
    parse_dotenv_lines,
    read_dotenv_file,
    validation_errors,
    write_dotenv_file,
)
from .admin_common import (
    admin_bearer_configured,
    can_access_admin_secrets,
    require_admin_action,
)

from ..utils.config import settings
from ..utils.codex_config_patch import apply_fc_init_codex_proxy_overrides
from ..utils.free_codex_paths import free_codex_config_toml
import logging
from ..services.sse_utils import usage_tracker

logger = logging.getLogger("free-codex")

router = APIRouter(prefix="/admin", tags=["admin"])


def _static_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "static" / "admin"


def _reveal_ok(request: Request) -> bool:
    return can_access_admin_secrets(request)


class EnvSaveBody(BaseModel):
    content: str = Field(..., description="Full .env text")


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
async def admin_page() -> HTMLResponse:
    index = _static_dir() / "index.html"
    if not index.is_file():
        return HTMLResponse("<p>Admin UI missing from package.</p>", status_code=500)
    return HTMLResponse(index.read_text(encoding="utf-8"))


@router.get("/api/env")
async def api_env_get(request: Request) -> JSONResponse:
    raw = read_dotenv_file()
    reveal = _reveal_ok(request)
    return JSONResponse(env_api_payload(raw_content=raw, reveal_secrets=reveal))


@router.post("/api/env")
async def api_env_post(request: Request, body: EnvSaveBody) -> JSONResponse:
    require_admin_action(request)

    errs = validation_errors(parse_dotenv_lines(body.content))
    if errs:
        raise HTTPException(status_code=400, detail={"validation_errors": errs})

    write_dotenv_file(body.content)
    # Reload settings to pick up changes without restart
    settings.reload()
    # Sync model to codex config.toml for CLI
    parsed = parse_dotenv_lines(body.content)
    model = (parsed.get("NVIDIA_NIM_MODEL") or "").strip()
    if model:
        cfg_path = free_codex_config_toml()
        if cfg_path.exists():
            try:
                raw = cfg_path.read_text(encoding="utf-8")
                patched = apply_fc_init_codex_proxy_overrides(raw, model=model)
                cfg_path.write_text(patched, encoding="utf-8")
            except Exception as e:
                logger.warning(f"Failed to sync model to config.toml: {e}")
        else:
            logger.warning(f"Codex config.toml not found at {cfg_path}, skipping model sync")
    else:
        logger.info("No NVIDIA_NIM_MODEL set in .env; config.toml unchanged")

    return JSONResponse(
        {
            "ok": True,
            "hint": "Settings reloaded. Restart fc-codex to pick up updated model in CLI.",
        }
    )


@router.get("/api/status")
async def api_status() -> JSONResponse:
    tok_set = bool(admin_bearer_configured())
    return JSONResponse(
        {
            "admin_token_configured": tok_set,
            "admin_local_fallback": not tok_set,
            "workspace_context_enabled": os.getenv("FREE_CODEX_WORKSPACE_CONTEXT", "")
            == "1",
        }
    )


@router.get("/api/usage")
async def admin_usage_stats() -> JSONResponse:
    # Return comprehensive stats: in-memory + persistent daily/monthly/streak
    stats = {
        **await usage_tracker.get_stats(),
        **get_persistent_stats(),
    }
    return JSONResponse(stats)
from ..services.sse_utils import usage_tracker, get_persistent_stats
