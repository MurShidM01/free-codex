"""OpenAI Chat/Completions routes backed by the provider-neutral router."""

from __future__ import annotations

import json
from typing import Any, AsyncGenerator, Dict

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from ..models import ChatCompletionRequest, CompletionRequest
from ..providers.base import ProviderError
from ..providers.router import ProviderRouter
from ..services.nim_service import NIMService
from ..services.sse_utils import sse_disconnect_safe

router = APIRouter()


async def get_nim_service(request: Request) -> NIMService:
    """Legacy dependency retained for integrations/tests that override NIM."""
    client = getattr(request.app.state, "http_client", None)
    if client is None:
        # TestClient can service a request without entering lifespan. Keep that
        # case usable without changing normal lifespan ownership.
        import httpx
        from ..utils.config import settings
        client = httpx.AsyncClient(
            timeout=httpx.Timeout(settings.read_timeout, connect=settings.connect_timeout)
        )
        request.app.state.http_client = client
    return NIMService(client)


async def get_provider_router(request: Request) -> ProviderRouter:
    provider_router = getattr(request.app.state, "provider_router", None)
    if provider_router is None:
        from ..providers.router import ProviderRouter as Router
        from ..utils.config import settings
        provider_router = Router(settings, getattr(request.app.state, "http_client", None))
        request.app.state.provider_router = provider_router
    elif getattr(provider_router, "client", None) is None and getattr(request.app.state, "http_client", None) is not None:
        provider_router.attach_client(request.app.state.http_client)
    return provider_router


def _dump(model: Any) -> Dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump(exclude_none=True)
    return model.dict(exclude_none=True)  # pragma: no cover - Pydantic v1 fallback


def _error_response(exc: ProviderError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content=exc.as_openai_error())


async def _chat_error_stream(exc: ProviderError) -> AsyncGenerator[bytes, None]:
    data = {"error": {"message": str(exc), "type": exc.error_type}}
    yield "data: {0}\n\n".format(json.dumps(data, separators=(",", ":"))).encode("utf-8")
    yield b"data: [DONE]\n\n"


def _legacy_override_active(raw_request: Request) -> bool:
    return get_nim_service in raw_request.app.dependency_overrides


@router.post("/chat/completions")
async def chat_completions(
    request: ChatCompletionRequest,
    raw_request: Request,
    nim_service: NIMService = Depends(get_nim_service),
    provider_router: ProviderRouter = Depends(get_provider_router),
):
    """Compatibility endpoint; clients still see only the stable local URL."""
    payload = _dump(request)
    if _legacy_override_active(raw_request):
        # Existing plugin/tests that inject NIMService retain byte-for-byte
        # behavior while production uses ProviderRouter.
        if request.stream:
            return StreamingResponse(
                sse_disconnect_safe(nim_service.stream_chat_completion(request)),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
            )
        return await nim_service.get_chat_completion(request)
    try:
        selection = provider_router.select(
            body=payload, requested_model=request.model, headers=dict(raw_request.headers)
        )
        if request.stream:
            async def generate() -> AsyncGenerator[bytes, None]:
                try:
                    async for chunk in provider_router.stream_chat_completion(selection, payload):
                        yield chunk
                except ProviderError as exc:
                    async for chunk in _chat_error_stream(exc):
                        yield chunk
            return StreamingResponse(
                sse_disconnect_safe(generate()),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
            )
        return await provider_router.chat_completion(selection, payload)
    except ProviderError as exc:
        return _error_response(exc)


@router.post("/completions")
async def completions(
    request: CompletionRequest,
    raw_request: Request,
    nim_service: NIMService = Depends(get_nim_service),
    provider_router: ProviderRouter = Depends(get_provider_router),
):
    """Legacy completions endpoint maintained for older OpenAI clients."""
    payload = _dump(request)
    if _legacy_override_active(raw_request):
        if request.stream:
            return StreamingResponse(
                sse_disconnect_safe(nim_service.stream_completion(request)),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
            )
        return await nim_service.get_completion(request)
    try:
        selection = provider_router.select(
            body=payload, requested_model=request.model, headers=dict(raw_request.headers)
        )
        if request.stream:
            async def generate() -> AsyncGenerator[bytes, None]:
                try:
                    async for chunk in provider_router.stream_completion(selection, payload):
                        yield chunk
                except ProviderError as exc:
                    async for chunk in _chat_error_stream(exc):
                        yield chunk
            return StreamingResponse(
                sse_disconnect_safe(generate()),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
            )
        return await provider_router.completion(selection, payload)
    except ProviderError as exc:
        return _error_response(exc)
