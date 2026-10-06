"""Preferred OpenAI Responses API route using the provider-neutral router."""

from __future__ import annotations

import json
from typing import Any, AsyncGenerator, Dict

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, StreamingResponse

from ..providers.base import ProviderError
from ..providers.router import ProviderRouter
from ..services.nim_chat_payload import normalize_chat_payload_for_nim
from ..services.nim_service import NIMService
from ..services.responses_bridge import (
    build_completed_response,
    chat_completion_assistant_content,
    chat_payload_from_responses_request,
    make_ids,
    response_skeleton,
)
from ..services.responses_output_items import output_from_chat_completion
from ..services.responses_messages import responses_body_to_chat_messages
from ..services.responses_stream import minimal_sse_from_completion, stream_responses_body
from ..services.sse_utils import sse_disconnect_safe
from ..services.workspace_inject import maybe_inject_workspace_context
from .chat import get_nim_service, get_provider_router

router = APIRouter()


def _legacy_override_active(request: Request) -> bool:
    return get_nim_service in request.app.dependency_overrides


def _headers() -> Dict[str, str]:
    return {
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
    }


def _provider_error_response(exc: ProviderError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content=exc.as_openai_error())


async def _responses_error_stream(
    exc: ProviderError,
    *,
    resp_id: str = "",
    displayed_model: str = "",
    req_body: Dict[str, Any] = None,
) -> AsyncGenerator[bytes, None]:
    data = {
        "type": "error",
        "error": {"type": exc.error_type, "message": str(exc)},
    }
    yield "event: error\ndata: {0}\n\n".format(json.dumps(data, separators=(",", ":"))).encode("utf-8")
    if resp_id and req_body is not None:
        failed = response_skeleton(resp_id, displayed_model, req_body)
        failed["status"] = "failed"
        failed["error"] = {"type": exc.error_type, "message": str(exc)}
        event = {"type": "response.failed", "sequence_number": 0, "response": failed}
        yield "event: response.failed\ndata: {0}\n\n".format(json.dumps(event, separators=(",", ":"))).encode("utf-8")
    yield b"data: [DONE]\n\n"


def _prepare(request: Request, body: Dict[str, Any]):
    messages, slug = responses_body_to_chat_messages(body)
    messages = maybe_inject_workspace_context(messages, body, request)
    payload = chat_payload_from_responses_request(body, messages, slug)
    return messages, slug, payload


@router.post("/responses")
async def create_response(
    request: Request,
    nim_service: NIMService = Depends(get_nim_service),
    provider_router: ProviderRouter = Depends(get_provider_router),
):
    """Translate Responses requests once, then dispatch to the selected provider."""
    body = await request.json()
    if not isinstance(body, dict):
        return JSONResponse(status_code=400, content={"error": {"message": "JSON object required", "type": "invalid_request_error"}})
    _, slug, payload = _prepare(request, body)
    resp_id, msg_id = make_ids()

    # Legacy injected NIMService remains a compatibility seam for users/tests
    # that embedded Free Codex before the provider router existed.
    if _legacy_override_active(request):
        normalize_chat_payload_for_nim(payload)
        display_model = ((body.get("model") or slug) or "nvidia_nim").strip()
        if payload.get("stream"):
            if hasattr(nim_service, "stream_chat_completions_payload"):
                stream = nim_service.stream_chat_completions_payload(dict(payload, stream=True))
                return StreamingResponse(
                    sse_disconnect_safe(stream_responses_body(
                        stream, resp_id=resp_id, msg_id=msg_id, displayed_model=display_model, req_body=body
                    )),
                    media_type="text/event-stream", headers=_headers(),
                )
            buffered = dict(payload)
            buffered["stream"] = False
            completion = await nim_service.post_chat_completions_payload(buffered)
            return StreamingResponse(
                sse_disconnect_safe(minimal_sse_from_completion(
                    completion=completion, resp_id=resp_id, msg_id=msg_id,
                    displayed_model=display_model, req_body=body,
                )),
                media_type="text/event-stream", headers=_headers(),
            )
        completion = await nim_service.post_chat_completions_payload(payload)
        out = output_from_chat_completion(completion)
        if out:
            return build_completed_response(
                resp_id=resp_id, msg_id=msg_id, model=display_model, req_body=body,
                assistant_text="", cc=completion, output=out,
            )
        return build_completed_response(
            resp_id=resp_id, msg_id=msg_id, model=display_model, req_body=body,
            assistant_text=chat_completion_assistant_content(completion), cc=completion,
        )

    try:
        selection = provider_router.select(
            body=body, requested_model=slug, headers=dict(request.headers)
        )
        # Preserve the local-facing requested alias/model in Responses objects;
        # the selected upstream model is visible in /v1/providers metadata.
        display_model = ((body.get("model") or slug) or selection.model).strip()
        payload["model"] = selection.model
        if payload.get("stream"):
            async def generate() -> AsyncGenerator[bytes, None]:
                try:
                    stream = provider_router.stream_chat_completion(selection, payload)
                    async for chunk in stream_responses_body(
                        stream, resp_id=resp_id, msg_id=msg_id,
                        displayed_model=display_model, req_body=body,
                    ):
                        yield chunk
                    provider_router.remember_response(resp_id, selection)
                except ProviderError as exc:
                    async for chunk in _responses_error_stream(
                        exc, resp_id=resp_id, displayed_model=display_model, req_body=body
                    ):
                        yield chunk
            return StreamingResponse(
                sse_disconnect_safe(generate()), media_type="text/event-stream", headers=_headers()
            )
        completion = await provider_router.chat_completion(selection, payload)
        provider_router.remember_response(resp_id, selection)
        out = output_from_chat_completion(completion)
        if out:
            return build_completed_response(
                resp_id=resp_id, msg_id=msg_id, model=display_model, req_body=body,
                assistant_text="", cc=completion, output=out,
            )
        return build_completed_response(
            resp_id=resp_id, msg_id=msg_id, model=display_model, req_body=body,
            assistant_text=chat_completion_assistant_content(completion), cc=completion,
        )
    except ProviderError as exc:
        return _provider_error_response(exc)


@router.post("/responses/stream")
async def create_response_stream(
    request: Request,
    nim_service: NIMService = Depends(get_nim_service),
    provider_router: ProviderRouter = Depends(get_provider_router),
):
    """Explicit streaming alias retained for clients that use it."""
    body = await request.json()
    if not isinstance(body, dict):
        return JSONResponse(status_code=400, content={"error": {"message": "JSON object required", "type": "invalid_request_error"}})
    _, slug, payload = _prepare(request, body)
    resp_id, msg_id = make_ids()
    payload["stream"] = True
    if _legacy_override_active(request):
        normalize_chat_payload_for_nim(payload)
        display_model = ((body.get("model") or slug) or "nvidia_nim").strip()
        if not hasattr(nim_service, "stream_chat_completions_payload"):
            return StreamingResponse(
                sse_disconnect_safe(_responses_error_stream(ProviderError("Legacy provider does not support streaming."))),
                media_type="text/event-stream", headers=_headers(),
            )
        return StreamingResponse(
            sse_disconnect_safe(stream_responses_body(
                nim_service.stream_chat_completions_payload(payload),
                resp_id=resp_id, msg_id=msg_id, displayed_model=display_model, req_body=body,
            )), media_type="text/event-stream", headers=_headers(),
        )
    try:
        selection = provider_router.select(body=body, requested_model=slug, headers=dict(request.headers))
        display_model = ((body.get("model") or slug) or selection.model).strip()
        payload["model"] = selection.model

        async def generate() -> AsyncGenerator[bytes, None]:
            try:
                async for chunk in stream_responses_body(
                    provider_router.stream_chat_completion(selection, payload),
                    resp_id=resp_id, msg_id=msg_id, displayed_model=display_model, req_body=body,
                ):
                    yield chunk
                provider_router.remember_response(resp_id, selection)
            except ProviderError as exc:
                async for chunk in _responses_error_stream(
                    exc, resp_id=resp_id, displayed_model=display_model, req_body=body
                ):
                    yield chunk

        return StreamingResponse(
            sse_disconnect_safe(generate()), media_type="text/event-stream", headers=_headers()
        )
    except ProviderError as exc:
        return StreamingResponse(
            sse_disconnect_safe(_responses_error_stream(exc)), media_type="text/event-stream",
            status_code=exc.status_code, headers=_headers(),
        )
