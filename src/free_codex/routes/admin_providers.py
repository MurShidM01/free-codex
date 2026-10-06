"""Sanitized provider administration endpoints."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from ..providers.puter_web import PuterWebProvider
from .admin_common import require_admin_action
from .chat import get_provider_router

router = APIRouter(prefix="/admin", tags=["admin", "providers"])


class ProviderToggleBody(BaseModel):
    enabled: bool


class ProviderSelectionBody(BaseModel):
    provider: str
    model: Optional[str] = None


@router.get("/api/providers")
async def admin_providers(request: Request) -> JSONResponse:
    provider_router = await get_provider_router(request)
    return JSONResponse({
        "default_provider": provider_router.settings.default_provider,
        "routing": provider_router.settings.routing.to_dict(),
        "providers": await provider_router.providers_status(probe=False),
        "recent_events": provider_router.event_logger.recent(),
    })


@router.get("/api/providers/logs")
async def admin_provider_logs(request: Request, limit: int = 25) -> JSONResponse:
    provider_router = await get_provider_router(request)
    return JSONResponse({"data": provider_router.event_logger.recent(limit)})


@router.get("/api/providers/{provider_id}")
async def admin_provider_detail(provider_id: str, request: Request) -> JSONResponse:
    provider_router = await get_provider_router(request)
    provider = provider_router.get_provider(provider_id)
    health = await provider.health(probe=False)
    data = provider.describe()
    data["health"] = health.to_dict()
    if isinstance(provider, PuterWebProvider):
        data["browser"] = provider.manager.status()
    return JSONResponse(data)


@router.post("/api/providers/{provider_id}/test")
async def admin_provider_test(provider_id: str, request: Request) -> JSONResponse:
    require_admin_action(request)
    provider_router = await get_provider_router(request)
    provider = provider_router.get_provider(provider_id)
    health = await provider.health(probe=True)
    return JSONResponse({"ok": health.ready, "health": health.to_dict()})


@router.post("/api/providers/{provider_id}/enabled")
async def admin_provider_enabled(
    provider_id: str, body: ProviderToggleBody, request: Request
) -> JSONResponse:
    """Enable/disable a provider for this running server session.

    Persistent configuration remains in providers.toml/.env so an admin action
    can never accidentally write a secret into browser-visible state.
    """
    require_admin_action(request)
    provider_router = await get_provider_router(request)
    provider = provider_router.get_provider(provider_id)
    provider.enabled = body.enabled
    return JSONResponse({
        "ok": True,
        "provider": provider.id,
        "enabled": provider.enabled,
        "hint": "Session-only change. Persist it in providers.toml before restarting fc-server.",
    })


@router.post("/api/providers/select")
async def admin_provider_select(body: ProviderSelectionBody, request: Request) -> JSONResponse:
    require_admin_action(request)
    provider_router = await get_provider_router(request)
    provider = provider_router.get_provider(body.provider)
    if not provider.enabled:
        raise HTTPException(status_code=400, detail="Provider is disabled.")
    # This is intentionally in-memory: it gives the local admin an immediate
    # selector without silently rewriting the user's routing file.
    provider_router.settings.routing.default_provider = provider.id
    if body.model:
        provider.default_model = body.model
    return JSONResponse({
        "ok": True,
        "default_provider": provider.id,
        "default_model": provider.default_model,
        "hint": "Session-only selection. Save [routing] and provider model settings in providers.toml to persist it.",
    })


@router.post("/api/providers/puter-web/auth")
async def admin_puter_auth(request: Request) -> JSONResponse:
    require_admin_action(request)
    provider_router = await get_provider_router(request)
    provider = provider_router.get_provider("puter_web")
    if not isinstance(provider, PuterWebProvider):  # defensive custom config case
        raise HTTPException(status_code=404, detail="Puter Web provider is not configured.")
    result = await provider.manager.begin_interactive_auth()
    return JSONResponse(result)


@router.get("/api/providers/puter-web/state")
async def admin_puter_state(request: Request) -> JSONResponse:
    provider_router = await get_provider_router(request)
    provider = provider_router.get_provider("puter_web")
    if not isinstance(provider, PuterWebProvider):
        raise HTTPException(status_code=404, detail="Puter Web provider is not configured.")
    return JSONResponse(provider.manager.status())
