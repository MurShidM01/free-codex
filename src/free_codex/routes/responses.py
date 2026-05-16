from fastapi import APIRouter, Request, Depends
from fastapi.responses import StreamingResponse

from ..services.nim_chat_payload import normalize_chat_payload_for_nim
from ..services.nim_service import NIMService
from ..services.responses_bridge import (
    build_completed_response,
    chat_completion_assistant_content,
    chat_payload_from_responses_request,
    make_ids,
)
from ..services.responses_buffered_sse import minimal_sse_from_completion
from ..services.responses_output_items import output_from_chat_completion
from ..services.responses_messages import responses_body_to_chat_messages
from ..services.stream_disconnect import sse_disconnect_safe
from ..services.workspace_inject import maybe_inject_workspace_context

router = APIRouter()


async def get_nim_service(request: Request) -> NIMService:
    return NIMService(request.app.state.http_client)


@router.post("/responses")
async def create_response(
    request: Request,
    nim_service: NIMService = Depends(get_nim_service),
):
    body = await request.json()
    messages, slug = responses_body_to_chat_messages(body)
    messages = maybe_inject_workspace_context(messages, body, request)
    display_model = ((body.get("model") or slug) or "nvidia_nim").strip()

    payload = chat_payload_from_responses_request(body, messages, slug)
    normalize_chat_payload_for_nim(payload)
    resp_id, msg_id = make_ids()

    if payload.get("stream"):
        buf = dict(payload)
        buf["stream"] = False
        completion = await nim_service.post_chat_completions_payload(buf)
        return StreamingResponse(
            sse_disconnect_safe(
                minimal_sse_from_completion(
                    completion,
                    resp_id=resp_id,
                    msg_id=msg_id,
                    displayed_model=display_model,
                    req_body=body,
                )
            ),
            media_type="text/event-stream",
        )

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
