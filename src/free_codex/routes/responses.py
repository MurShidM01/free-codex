"""Responses API route with advanced SSE streaming support."""

from fastapi import APIRouter, Request, Depends
from fastapi.responses import StreamingResponse

from ..services.nim_service import NIMService
from ..services.nim_chat_payload import normalize_chat_payload_for_nim
from ..services.responses_bridge import (
    build_completed_response,
    chat_completion_assistant_content,
    chat_payload_from_responses_request,
    make_ids,
)
from ..services.responses_stream import stream_responses_body, minimal_sse_from_completion
from ..services.responses_output_items import output_from_chat_completion
from ..services.responses_messages import responses_body_to_chat_messages
from ..services.sse_utils import sse_disconnect_safe
from ..services.workspace_inject import maybe_inject_workspace_context

router = APIRouter()


async def get_nim_service(request: Request) -> NIMService:
    return NIMService(request.app.state.http_client)


@router.post("/responses")
async def create_response(
    request: Request,
    nim_service: NIMService = Depends(get_nim_service),
):
    """Handle OpenAI Responses API requests.

    Supports both streaming and non-streaming responses.
    Maps OpenAI Responses format to NIM-compatible Chat Completions.
    """
    body = await request.json()
    messages, slug = responses_body_to_chat_messages(body)
    messages = maybe_inject_workspace_context(messages, body, request)
    display_model = ((body.get("model") or slug) or "nvidia_nim").strip()

    payload = chat_payload_from_responses_request(body, messages, slug)
    normalize_chat_payload_for_nim(payload)
    resp_id, msg_id = make_ids()

    # Check if streaming is requested
    if payload.get("stream"):
        # For streaming, we still call non-streaming NIM and convert to SSE
        # This ensures compatibility with NIM endpoints that don't support streaming
        buf = dict(payload)
        buf["stream"] = False

        # Start streaming SSE response
        return StreamingResponse(
            sse_disconnect_safe(
                minimal_sse_from_completion(
                    completion=buf,
                    resp_id=resp_id,
                    msg_id=msg_id,
                    displayed_model=display_model,
                    req_body=body,
                )
            ),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    # Non-streaming response
    completion = await nim_service.post_chat_completions_payload(payload)
    out = output_from_chat_completion(completion)

    if out:
        return build_completed_response(
            resp_id=resp_id,
            msg_id=msg_id,
            model=display_model,
            req_body=body,
            assistant_text="",
            cc=completion,
            output=out,
        )

    text = chat_completion_assistant_content(completion)
    return build_completed_response(
        resp_id=resp_id,
        msg_id=msg_id,
        model=display_model,
        req_body=body,
        assistant_text=text,
        cc=completion,
    )


@router.post("/responses/stream")
async def create_response_stream(
    request: Request,
    nim_service: NIMService = Depends(get_nim_service),
):
    """Dedicated streaming endpoint for /v1/responses with true SSE streaming.

    This endpoint forwards streaming requests to NIM and converts
    the SSE stream to OpenAI Responses format.
    """
    body = await request.json()
    messages, slug = responses_body_to_chat_messages(body)
    messages = maybe_inject_workspace_context(messages, body, request)
    display_model = ((body.get("model") or slug) or "nvidia_nim").strip()

    payload = chat_payload_from_responses_request(body, messages, slug)
    normalize_chat_payload_for_nim(payload)
    resp_id, msg_id = make_ids()

    # Enable streaming on NIM side
    stream_payload = dict(payload)
    stream_payload["stream"] = True

    try:
        # Get streaming response from NIM
        stream = nim_service.stream_chat_completions_payload(stream_payload)

        return StreamingResponse(
            sse_disconnect_safe(
                stream_responses_body(
                    stream,
                    resp_id=resp_id,
                    msg_id=msg_id,
                    displayed_model=display_model,
                    req_body=body,
                )
            ),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )
    except Exception as e:
        return StreamingResponse(
            sse_disconnect_safe(
                _error_stream(str(e))
            ),
            media_type="text/event-stream",
            status_code=500,
        )


async def _error_stream(error: str):
    """Yield an error response as SSE."""
    import json
    error_data = {
        "type": "error",
        "error": {
            "type": "server_error",
            "message": error,
        },
    }
    yield f"data: {json.dumps(error_data)}\n\n".encode()
    yield b"data: [DONE]\n\n"