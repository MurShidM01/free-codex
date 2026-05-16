"""Chat Completions routes with improved SSE streaming."""

from fastapi import APIRouter, Request, HTTPException, Depends
from fastapi.responses import StreamingResponse
from ..models import ChatCompletionRequest, CompletionRequest
from ..services.nim_service import NIMService
from ..services.sse_utils import sse_disconnect_safe

router = APIRouter()


async def get_nim_service(request: Request) -> NIMService:
    return NIMService(request.app.state.http_client)


@router.post("/chat/completions")
async def chat_completions(
    request: ChatCompletionRequest,
    raw_request: Request,
    nim_service: NIMService = Depends(get_nim_service),
):
    """Handle /v1/chat/completions requests.

    Supports both streaming and non-streaming responses.
    Maps to NVIDIA NIM compatible chat completions.
    """
    if request.stream:
        return StreamingResponse(
            sse_disconnect_safe(nim_service.stream_chat_completion(request)),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )
    else:
        return await nim_service.get_chat_completion(request)


@router.post("/completions")
async def completions(
    request: CompletionRequest,
    raw_request: Request,
    nim_service: NIMService = Depends(get_nim_service),
):
    """Handle /v1/completions requests.

    Supports both streaming and non-streaming text completions.
    """
    if request.stream:
        return StreamingResponse(
            sse_disconnect_safe(nim_service.stream_completion(request)),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )
    else:
        return await nim_service.get_completion(request)