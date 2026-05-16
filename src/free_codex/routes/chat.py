import json
from fastapi import APIRouter, Request, HTTPException, Depends
from fastapi.responses import StreamingResponse
from ..models import ChatCompletionRequest, CompletionRequest
from ..services.nim_service import NIMService

router = APIRouter()

async def get_nim_service(request: Request) -> NIMService:
    return NIMService(request.app.state.http_client)

@router.post("/chat/completions")
async def chat_completions(
    request: ChatCompletionRequest, 
    raw_request: Request,
    nim_service: NIMService = Depends(get_nim_service)
):
    # Log the incoming request for debugging/advancement
    print(f"INFO: Chat completion request for model: {request.model}")
    
    if request.stream:
        return StreamingResponse(
            nim_service.stream_chat_completion(request),
            media_type="text/event-stream"
        )
    else:
        return await nim_service.get_chat_completion(request)

@router.post("/completions")
async def completions(
    request: CompletionRequest, 
    raw_request: Request,
    nim_service: NIMService = Depends(get_nim_service)
):
    # Log the incoming request for debugging/advancement
    print(f"INFO: Completion request for model: {request.model}")
    
    if request.stream:
        return StreamingResponse(
            nim_service.stream_completion(request),
            media_type="text/event-stream"
        )
    else:
        return await nim_service.get_completion(request)
