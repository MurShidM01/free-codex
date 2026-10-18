"""Provider-aware model and capability discovery endpoints."""

from __future__ import annotations

import time
from typing import Any, Dict

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from .chat import get_provider_router

router = APIRouter()


@router.get("/models")
async def list_models(request: Request) -> JSONResponse:
    """List local aliases and provider/model metadata without secrets."""
    provider_router = await get_provider_router(request)
    # Configured models are instant and deterministic. Remote discovery is
    # intentionally opt-in so /v1/models never blocks Codex startup.
    discover = request.query_params.get("discover", "").lower() in ("1", "true", "yes")
    models = await provider_router.list_models(discover=discover)
    now = int(time.time())
    data = []
    for model in models:
        row = dict(model)
        row.setdefault("object", "model")
        row.setdefault("created", now)
        data.append(row)
    return JSONResponse({"object": "list", "data": data})


@router.get("/providers")
async def list_providers(request: Request) -> JSONResponse:
    """Expose sanitized router/provider state for local clients and admin UI."""
    provider_router = await get_provider_router(request)
    probe = request.query_params.get("probe", "").lower() in ("1", "true", "yes")
    return JSONResponse({
        "object": "list",
        "default_provider": provider_router.settings.default_provider,
        "routing": provider_router.settings.routing.to_dict(),
        "data": await provider_router.providers_status(probe=probe),
    })


@router.get("/providers/{provider_id}")
async def provider_details(provider_id: str, request: Request) -> JSONResponse:
    provider_router = await get_provider_router(request)
    provider = provider_router.get_provider(provider_id)
    health = await provider.health(probe=False)
    data: Dict[str, Any] = provider.describe()
    data["health"] = health.to_dict()
    return JSONResponse(data)
