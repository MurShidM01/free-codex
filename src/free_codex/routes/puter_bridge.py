"""Private localhost-only bridge endpoint for the hidden Puter.js page."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, PlainTextResponse

from ..providers.base import ProviderProtocolError

router = APIRouter(tags=["internal"])


def _manager_from_app(app):
    provider_router = getattr(app.state, "provider_router", None)
    if provider_router is None:
        return None
    return provider_router.puter_browser_manager


def _is_local_client(host: str) -> bool:
    return (host or "").split("%", 1)[0].lower() in (
        "127.0.0.1", "::1", "localhost", "testclient"
    )


def _bridge_html() -> str:
    path = Path(__file__).resolve().parent.parent / "static" / "bridge" / "puter_bridge.html"
    return path.read_text(encoding="utf-8")


@router.get("/internal/puter-bridge/{session_id}", include_in_schema=False)
async def puter_bridge_page(session_id: str, request: Request):
    """Serve the deliberately minimal SDK worker page only to a valid session."""
    manager = _manager_from_app(request.app)
    nonce = request.query_params.get("nonce", "")
    host = request.client.host if request.client else ""
    request_host = request.headers.get("host", "")
    if (
        manager is None
        or not _is_local_client(host)
        or not manager._host_is_local(request_host)
        or not manager.validate_page_session(session_id, nonce)
    ):
        # Do not reveal whether a session exists to a remote caller.
        return PlainTextResponse("Not found", status_code=404)
    return HTMLResponse(
        _bridge_html(),
        headers={
            "Cache-Control": "no-store",
            "Referrer-Policy": "no-referrer",
            "X-Frame-Options": "DENY",
            "Content-Security-Policy": (
                "default-src 'none'; script-src 'self' https://js.puter.com; "
                "connect-src 'self' https://js.puter.com wss: ws:; "
                "style-src 'self' 'unsafe-inline'; base-uri 'none'; frame-ancestors 'none'"
            ),
        },
    )


@router.websocket("/internal/puter-bridge/{session_id}/ws")
async def puter_bridge_socket(websocket: WebSocket, session_id: str) -> None:
    manager = _manager_from_app(websocket.app)
    nonce = websocket.query_params.get("nonce", "")
    origin = websocket.headers.get("origin", "")
    host = websocket.headers.get("host", "")
    client_host = websocket.client.host if websocket.client else ""
    if manager is None or not _is_local_client(client_host):
        await websocket.close(code=1008)
        return
    if not manager.validate_page_session(session_id, nonce):
        await websocket.close(code=1008)
        return
    await websocket.accept()
    session = None
    sender = None
    try:
        session = await manager.attach_websocket(
            websocket, session_id=session_id, nonce=nonce, origin=origin, host=host
        )
        sender = __import__("asyncio").create_task(manager.bridge_sender(session, websocket))
        while True:
            message = await websocket.receive_json()
            await manager.receive_bridge_message(session, message)
    except WebSocketDisconnect:
        pass
    except ProviderProtocolError:
        await websocket.close(code=1008)
    except Exception:
        # Details stay in server logs; no browser prompt/token is logged.
        await websocket.close(code=1011)
    finally:
        if sender:
            sender.cancel()
        if session:
            await manager.detach_websocket(session, websocket)
