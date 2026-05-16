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
    return JSONResponse(
        {
            "ok": True,
            "hint": "Restart fc-server so running workers reload NVIDIA_* variables from disk.",
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
