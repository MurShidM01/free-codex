"""Admin endpoints that probe the remote NVIDIA / OpenAI-compatible API."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from ..services.admin_env import parse_dotenv_lines, read_dotenv_file
from ..services.admin_nim_probe import nim_fetch_models, nim_ping_chat
from .admin_common import can_access_admin_secrets, require_admin_action

router = APIRouter(prefix="/admin", tags=["admin"])


class NimProbeFields(BaseModel):
    api_key: Optional[str] = Field(None, description="Override API key")
    base_url: Optional[str] = Field(None, description="Override base URL")
    model: Optional[str] = Field(None, description="Model id for chat test")


def _disk_env() -> dict[str, str]:
    return parse_dotenv_lines(read_dotenv_file())


def _merge_base_key(body: NimProbeFields) -> tuple[str, str]:
    d = _disk_env()
    base = (body.base_url or d.get("NVIDIA_NIM_BASE_URL") or "").strip()
    key = (body.api_key or d.get("NVIDIA_NIM_API_KEY") or "").strip()
    if not base:
        raise HTTPException(
            status_code=400,
            detail="Missing base URL (form or NVIDIA_NIM_BASE_URL in .env).",
        )
    if not key:
        raise HTTPException(
            status_code=400,
            detail="Missing API key (form or NVIDIA_NIM_API_KEY in .env).",
        )
    return base, key


def _merge_model(body: NimProbeFields) -> str:
    d = _disk_env()
    model = (body.model or d.get("NVIDIA_NIM_MODEL") or "").strip()
    if not model:
        raise HTTPException(
            status_code=400,
            detail="Missing model (form or NVIDIA_NIM_MODEL in .env).",
        )
    return model


@router.get("/api/nim/defaults")
async def admin_nim_defaults(request: Request) -> JSONResponse:
    d = _disk_env()
    model = (d.get("NVIDIA_NIM_MODEL") or "").strip()
    if not model:
        model = "gpt-5.5"

    if not can_access_admin_secrets(request):
        # Unauthenticated: only return model, no secrets
        return JSONResponse({"model": model})

    # Authenticated: return full config
    return JSONResponse(
        {
            "base_url": (d.get("NVIDIA_NIM_BASE_URL") or "").strip(),
            "api_key": (d.get("NVIDIA_NIM_API_KEY") or "").strip(),
            "model": model,
        }
    )


@router.post("/api/nim/models")
async def admin_nim_models(request: Request, body: NimProbeFields) -> JSONResponse:
    require_admin_action(request)
    base, key = _merge_base_key(body)
    client = request.app.state.http_client
    result = await nim_fetch_models(client, base_url=base, api_key=key)
    return JSONResponse(result)


@router.post("/api/nim/test")
async def admin_nim_test(request: Request, body: NimProbeFields) -> JSONResponse:
    require_admin_action(request)
    base, key = _merge_base_key(body)
    model = _merge_model(body)
    client = request.app.state.http_client
    result = await nim_ping_chat(client, base_url=base, api_key=key, model=model)
    return JSONResponse(result)
