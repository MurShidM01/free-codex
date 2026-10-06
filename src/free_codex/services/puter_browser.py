"""Managed, local-only browser bridge for the official Puter.js SDK.

This module does *not* call Puter's OpenAI HTTP endpoint and does not inspect
cookies or private site APIs.  It launches a persistent Chromium context, loads
a tiny local bridge page containing ``https://js.puter.com/v2/``, and exchanges
serialized provider requests over a nonce-bound localhost WebSocket.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import secrets
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, AsyncGenerator, Dict, Optional
from urllib.parse import urlparse

from ..providers.base import (
    ProviderAuthenticationRequiredError,
    ProviderProtocolError,
    ProviderUnavailableError,
)
from ..utils.config import ProviderDefinition
from .provider_logging import ProviderEventLogger

logger = logging.getLogger("free-codex.puter_browser")


@dataclass
class PendingBrowserRequest:
    request_id: str
    queue: "asyncio.Queue[Dict[str, Any]]"
    created_at: float
    timeout: float
    conversation_id: str = ""
    cancelled: bool = False


@dataclass
class BridgeSession:
    session_id: str
    nonce: str
    expires_at: float
    expected_origin: str
    outgoing: "asyncio.Queue[Dict[str, Any]]" = field(default_factory=asyncio.Queue)
    connected: asyncio.Event = field(default_factory=asyncio.Event)
    ready: asyncio.Event = field(default_factory=asyncio.Event)
    websocket: Any = None
    active_connection_id: str = ""
    authenticated: Optional[bool] = None
    sdk_ready: bool = False
    last_heartbeat: float = field(default_factory=time.monotonic)
    last_error: str = ""
    state: str = "starting"


class PuterBrowserManager:
    """Owns one hidden persistent browser bridge and correlated request queues.

    A single browser context is intentional: it keeps authentication in a user
    owned persistent profile while avoiding a visible Puter app/tab during
    normal requests.  A semaphore controls concurrent model requests.
    """

    def __init__(
        self,
        definition: ProviderDefinition,
        *,
        bridge_base_url: str = "",
        event_logger: Optional[ProviderEventLogger] = None,
        playwright_factory: Any = None,
    ) -> None:
        self.definition = definition
        self.options = dict(definition.options)
        self.bridge_base_url = bridge_base_url.rstrip("/")
        self.event_logger = event_logger or ProviderEventLogger()
        self._playwright_factory = playwright_factory
        self._playwright: Any = None
        self._context: Any = None
        self._page: Any = None
        self._session: Optional[BridgeSession] = None
        self._pending: Dict[str, PendingBrowserRequest] = {}
        self._lock = asyncio.Lock()
        self._maintenance_task: Optional[asyncio.Task[Any]] = None
        self._stopped = False
        max_concurrency = definition.max_concurrent_requests or 1
        self._request_slots = asyncio.Semaphore(max(1, max_concurrency))
        self._last_error = ""
        self._reconnect_count = 0

    @property
    def profile_dir(self) -> Path:
        raw = str(self.options.get("profile_dir") or "").strip()
        if raw:
            return Path(raw).expanduser()
        from ..utils.free_codex_paths import free_codex_dir
        return free_codex_dir() / "puter-profile"

    @property
    def connect_timeout(self) -> int:
        return max(1, int(self.options.get("connect_timeout") or 30))

    @property
    def session_timeout(self) -> int:
        return max(30, int(self.options.get("session_timeout") or 3600))

    @property
    def request_timeout(self) -> int:
        return max(10, int(self.options.get("request_timeout") or 900))

    @property
    def headless(self) -> bool:
        value = self.options.get("headless", True)
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in ("1", "true", "yes", "on")

    def set_bridge_base_url(self, value: str) -> None:
        if value:
            self.bridge_base_url = value.rstrip("/")

    def _bridge_origin(self) -> str:
        if self.bridge_base_url:
            parsed = urlparse(self.bridge_base_url)
            if parsed.scheme and parsed.netloc:
                return "{0}://{1}".format(parsed.scheme, parsed.netloc)
        # fc-server's default external/local path.  This is intentionally
        # loopback even when Uvicorn binds 0.0.0.0.
        port = os.getenv("FREE_CODEX_PORT", "8080")
        return "http://127.0.0.1:{0}".format(port)

    def _new_session(self) -> BridgeSession:
        origin = self._bridge_origin()
        return BridgeSession(
            session_id=secrets.token_urlsafe(32),
            nonce=secrets.token_urlsafe(48),
            expires_at=time.monotonic() + self.session_timeout,
            expected_origin=origin,
        )

    def bridge_page_url(self, session: Optional[BridgeSession] = None, auth: bool = False) -> str:
        current = session or self._session
        if current is None:
            raise ProviderUnavailableError("Puter browser bridge has not been initialized.")
        suffix = "/internal/puter-bridge/{0}?nonce={1}".format(current.session_id, current.nonce)
        if auth:
            suffix += "&auth=1"
        return current.expected_origin + suffix

    async def _load_playwright(self) -> Any:
        if self._playwright is not None:
            return self._playwright
        try:
            if self._playwright_factory is not None:
                candidate = self._playwright_factory()
                self._playwright = await candidate if hasattr(candidate, "__await__") else candidate
            else:
                from playwright.async_api import async_playwright  # type: ignore
                self._playwright = await async_playwright().start()
            return self._playwright
        except ImportError as exc:
            self._last_error = "Puter Web is not initialized; install Playwright and run fc-puter-auth."
            raise ProviderUnavailableError(
                "Puter Web is unavailable because browser automation is not installed. "
                "Install it with: pip install 'free-codex[puter]' and python -m playwright install chromium."
            ) from exc
        except Exception as exc:
            self._last_error = "Could not start Playwright"
            raise ProviderUnavailableError(
                "Puter Web browser runtime could not start. Install a supported Chromium browser or configure PUTER_WEB_BROWSER."
            ) from exc

    async def _launch_context(self, *, headless: Optional[bool] = None) -> Any:
        pw = await self._load_playwright()
        browser_name = str(self.options.get("browser") or "chromium").strip()
        browser = getattr(pw, "chromium", None)
        if browser is None:
            raise ProviderUnavailableError("Playwright Chromium support is unavailable.")
        profile = self.profile_dir
        profile.mkdir(parents=True, exist_ok=True)
        try:
            # Best-effort owner-only permissions on POSIX. Windows ACLs are
            # managed by the profile owner/OS and are not weakened here.
            if os.name != "nt":
                os.chmod(str(profile), 0o700)
        except OSError:
            pass
        options: Dict[str, Any] = {"headless": self.headless if headless is None else headless}
        lowered = browser_name.lower()
        if lowered in ("chrome", "google-chrome", "msedge", "edge"):
            options["channel"] = "chrome" if "chrome" in lowered else "msedge"
        elif lowered not in ("chromium", "playwright", "default"):
            # A filesystem path is supported; unknown strings retain Playwright
            # Chromium rather than executing an arbitrary command.
            candidate = Path(browser_name).expanduser()
            if candidate.exists():
                options["executable_path"] = str(candidate)
        configured_path = str(self.options.get("executable_path") or "").strip()
        if configured_path and Path(configured_path).expanduser().exists():
            options["executable_path"] = str(Path(configured_path).expanduser())
        try:
            return await browser.launch_persistent_context(str(profile), **options)
        except Exception as exc:
            self._last_error = "Puter Web Chromium launch failed; install Chromium or configure PUTER_WEB_BROWSER."
            raise ProviderUnavailableError(
                "Puter Web could not launch Chromium. Run 'python -m playwright install chromium' "
                "or set PUTER_WEB_BROWSER to a supported executable path."
            ) from exc

    def _bind_page_events(self, page: Any) -> None:
        # Page event handlers only update state; they never read page content,
        # cookies, prompts, or authentication material.
        try:
            page.on("crash", lambda: self._schedule_bridge_failure("Browser page crashed."))
            page.on("close", lambda: self._schedule_bridge_failure("Browser page closed."))
            page.on("framenavigated", self._on_frame_navigated)
        except Exception:
            # Fake page objects used by unit tests may intentionally omit .on.
            pass

    def _on_frame_navigated(self, frame: Any) -> None:
        try:
            url = str(getattr(frame, "url", ""))
            if url and "/internal/puter-bridge/" not in url:
                self._schedule_bridge_failure("Puter bridge page navigated unexpectedly.")
        except Exception:
            return

    def _schedule_bridge_failure(self, message: str) -> None:
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self.mark_disconnected(message))
        except RuntimeError:
            pass

    async def start(self, *, wait_for_connection: bool = True, headless: Optional[bool] = None) -> None:
        if not self.definition.enabled:
            raise ProviderUnavailableError("Puter Web is disabled (set PUTER_WEB_ENABLED=1 to enable it).")
        self._stopped = False
        async with self._lock:
            if self._session and self._session.connected.is_set() and self._page is not None:
                return
            # Stale resources are closed before a recovery launch.
            if self._session is not None:
                self._reconnect_count += 1
            await self._close_browser_resources()
            session = self._new_session()
            self._session = session
            session.state = "starting_browser"
            self.event_logger.event("browser_starting", provider=self.definition.id, status=session.state)
            self._context = await self._launch_context(headless=headless)
            pages = getattr(self._context, "pages", []) or []
            self._page = pages[0] if pages else await self._context.new_page()
            self._bind_page_events(self._page)
            try:
                await self._page.goto(self.bridge_page_url(session), wait_until="domcontentloaded")
            except Exception as exc:
                await self._close_browser_resources()
                session.state = "error"
                session.last_error = "Bridge page could not load"
                self._last_error = session.last_error
                raise ProviderUnavailableError(
                    "Puter Web browser started but its local bridge page could not connect."
                ) from exc
            if self._maintenance_task is None or self._maintenance_task.done():
                self._maintenance_task = asyncio.create_task(self._maintenance_loop())
        if wait_for_connection:
            try:
                await asyncio.wait_for(session.connected.wait(), timeout=self.connect_timeout)
            except asyncio.TimeoutError as exc:
                session.state = "bridge_timeout"
                session.last_error = "Timed out waiting for local browser bridge"
                self._last_error = session.last_error
                raise ProviderUnavailableError(
                    "Puter Web browser bridge did not connect. Ensure fc-server is reachable on localhost."
                ) from exc

    async def ensure_ready(self, *, require_auth: bool = True) -> BridgeSession:
        if self._session is None or not self._session.connected.is_set():
            await self.start(wait_for_connection=True)
        session = self._session
        if session is None:
            raise ProviderUnavailableError("Puter Web browser bridge is unavailable.")
        try:
            await asyncio.wait_for(session.ready.wait(), timeout=self.connect_timeout)
        except asyncio.TimeoutError as exc:
            raise ProviderUnavailableError("Puter Web browser bridge is connected but Puter.js is not ready.") from exc
        if require_auth and session.authenticated is not True:
            raise ProviderAuthenticationRequiredError(
                "Puter Web is not authenticated; run fc-puter-auth, complete the one-time sign-in, then retry."
            )
        return session

    def _session_valid(self, session_id: str, nonce: str) -> Optional[BridgeSession]:
        session = self._session
        if session is None:
            return None
        if time.monotonic() >= session.expires_at:
            return None
        if not secrets.compare_digest(session.session_id, str(session_id or "")):
            return None
        if not secrets.compare_digest(session.nonce, str(nonce or "")):
            return None
        return session

    def validate_page_session(self, session_id: str, nonce: str) -> bool:
        """Used by the HTTP bridge page route before returning any HTML."""
        return self._session_valid(session_id, nonce) is not None

    @staticmethod
    def _origin_is_local(origin: str) -> bool:
        # Browser WebSockets supply Origin. Treating an omitted Origin as valid
        # would weaken the bridge command boundary for non-browser clients.
        if not origin:
            return False
        parsed = urlparse(origin)
        host = (parsed.hostname or "").lower()
        return host in ("127.0.0.1", "localhost", "::1", "testserver")

    @staticmethod
    def _host_is_local(host_header: str) -> bool:
        raw = (host_header or "").strip().lower()
        if raw.startswith("["):
            host = raw[1:].split("]", 1)[0]
        else:
            host = raw.rsplit(":", 1)[0] if raw.count(":") == 1 else raw
        return host in ("127.0.0.1", "localhost", "::1", "testserver")

    async def attach_websocket(
        self,
        websocket: Any,
        *,
        session_id: str,
        nonce: str,
        origin: str = "",
        host: str = "",
    ) -> BridgeSession:
        session = self._session_valid(session_id, nonce)
        if session is None:
            raise ProviderProtocolError("Invalid or expired Puter bridge session.")
        expected = session.expected_origin.rstrip("/")
        if (
            not self._origin_is_local(origin)
            or not self._host_is_local(host)
            or (origin and origin.rstrip("/") != expected)
        ):
            raise ProviderProtocolError("Puter bridge rejected a non-local origin or host.")
        if session.websocket is not None:
            # One active consumer protects the browser command channel from
            # replayed or competing bridge pages.
            raise ProviderProtocolError("A Puter browser bridge is already connected.")
        session.websocket = websocket
        session.active_connection_id = secrets.token_urlsafe(18)
        session.connected.set()
        session.state = "connected"
        session.last_heartbeat = time.monotonic()
        self.event_logger.event("browser_connected", provider=self.definition.id, status="connected")
        return session

    async def detach_websocket(
        self, session: BridgeSession, websocket: Any = None, reason: str = "Browser bridge disconnected."
    ) -> None:
        # A navigation can create a replacement socket before the old socket's
        # finally block runs. Only the active socket may detach the session.
        if self._session is session and (websocket is None or session.websocket is websocket):
            session.websocket = None
            session.active_connection_id = ""
            session.connected.clear()
            session.ready.clear()
            session.state = "disconnected"
            session.last_error = reason
            self._last_error = reason
            self.event_logger.event("browser_disconnected", provider=self.definition.id, status="disconnected")
            await self._fail_pending(ProviderUnavailableError("Puter Web browser bridge disconnected."))

    async def bridge_sender(self, session: BridgeSession, websocket: Any) -> None:
        """Send trusted backend commands to the page until it disconnects."""
        while self._session is session and session.websocket is websocket:
            command = await session.outgoing.get()
            await websocket.send_json(command)

    async def receive_bridge_message(self, session: BridgeSession, message: Dict[str, Any]) -> None:
        if not isinstance(message, dict):
            raise ProviderProtocolError("Puter bridge sent malformed JSON.")
        kind = str(message.get("type") or "")
        session.last_heartbeat = time.monotonic()
        if kind == "hello":
            # The page has already proven possession of the nonce during the
            # WebSocket handshake. Do not echo it or any profile state back.
            await session.outgoing.put({"type": "hello_ack", "session_id": session.session_id})
            return
        if kind == "ready":
            session.sdk_ready = bool(message.get("sdk_ready", True))
            auth = message.get("authenticated")
            session.authenticated = auth if isinstance(auth, bool) else False
            session.state = "ready" if session.sdk_ready else "sdk_error"
            if isinstance(message.get("error"), str):
                session.last_error = message["error"][:300]
                self._last_error = session.last_error
            session.ready.set()
            self.event_logger.event(
                "puter_authenticated" if session.authenticated else "puter_auth_required",
                provider=self.definition.id,
                status=session.state,
            )
            return
        if kind == "heartbeat" or kind == "pong":
            return
        request_id = str(message.get("request_id") or "")
        if not request_id or request_id not in self._pending:
            # Ignore late/replayed browser messages; they must never be routed
            # to a new request merely because IDs were guessed.
            return
        pending = self._pending[request_id]
        event = message.get("event")
        if not isinstance(event, dict):
            if kind in ("error", "completed", "cancelled"):
                event = {"type": kind, "error": message.get("error")}
            else:
                raise ProviderProtocolError("Puter bridge event is malformed.")
        await pending.queue.put(event)

    async def request_events(
        self,
        payload: Dict[str, Any],
        *,
        request_id: Optional[str] = None,
        timeout: Optional[float] = None,
        conversation_id: str = "",
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """Send one serialized Puter.js request and yield its safe events."""
        session = await self.ensure_ready(require_auth=True)
        rid = request_id or "puter_{0}".format(uuid.uuid4().hex)
        if rid in self._pending:
            raise ProviderProtocolError("Duplicate active Puter request id.")
        await self._request_slots.acquire()
        pending = PendingBrowserRequest(
            request_id=rid,
            queue=asyncio.Queue(),
            created_at=time.monotonic(),
            timeout=float(timeout or self.request_timeout),
            conversation_id=conversation_id,
        )
        self._pending[rid] = pending
        command = {
            "type": "request",
            "request_id": rid,
            "conversation_id": conversation_id,
            "request": payload,
        }
        await session.outgoing.put(command)
        self.event_logger.event(
            "stream_started", request_id=rid, provider=self.definition.id,
            model=str(payload.get("model") or ""), protocol="puter_web", stream=bool(payload.get("stream")), status="started",
        )
        deadline = time.monotonic() + pending.timeout
        completed = False
        try:
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise ProviderUnavailableError("Puter Web request timed out.")
                try:
                    event = await asyncio.wait_for(pending.queue.get(), timeout=remaining)
                except asyncio.TimeoutError as exc:
                    raise ProviderUnavailableError("Puter Web request timed out.") from exc
                event_type = str(event.get("type") or "")
                if event_type == "error":
                    detail = event.get("error")
                    message = "Puter Web request failed."
                    if isinstance(detail, dict) and isinstance(detail.get("message"), str):
                        message = detail["message"][:500]
                    elif isinstance(detail, str):
                        message = detail[:500]
                    raise ProviderUnavailableError(message)
                yield event
                if event_type in ("completed", "cancelled"):
                    completed = True
                    self.event_logger.event(
                        "response_completed", request_id=rid, provider=self.definition.id,
                        model=str(payload.get("model") or ""), protocol="puter_web", stream=bool(payload.get("stream")), status=event_type,
                    )
                    break
        finally:
            self._pending.pop(rid, None)
            self._request_slots.release()
            if not completed and not pending.cancelled:
                # Cancellation is propagated when the HTTP/SSE consumer leaves
                # early or a timeout/error interrupts the round trip.
                await self.cancel(rid)

    async def cancel(self, request_id: str) -> None:
        pending = self._pending.get(request_id)
        if pending:
            pending.cancelled = True
        session = self._session
        if session and session.connected.is_set():
            with contextlib.suppress(Exception):
                await session.outgoing.put({"type": "cancel", "request_id": request_id})
        self.event_logger.event("request_cancelled", request_id=request_id, provider=self.definition.id, status="cancelled")

    async def _fail_pending(self, error: Exception) -> None:
        for pending in list(self._pending.values()):
            await pending.queue.put({"type": "error", "error": {"message": str(error)}})

    async def mark_disconnected(self, reason: str) -> None:
        session = self._session
        if session:
            session.websocket = None
            session.connected.clear()
            session.ready.clear()
            session.state = "disconnected"
            session.last_error = reason[:300]
        self._last_error = reason[:300]
        await self._fail_pending(ProviderUnavailableError("Puter Web browser runtime disconnected."))

    async def _maintenance_loop(self) -> None:
        try:
            while not self._stopped:
                await asyncio.sleep(5)
                session = self._session
                if session is None:
                    continue
                now = time.monotonic()
                if now >= session.expires_at:
                    await self.mark_disconnected("Puter browser bridge session expired.")
                    continue
                # A browser bridge with no heartbeat for two session windows is
                # failed rather than allowed to leave Codex waiting forever.
                if session.connected.is_set() and now - session.last_heartbeat > min(self.session_timeout, 120):
                    await self.mark_disconnected("Puter browser bridge heartbeat timed out.")
                    continue
                if session.connected.is_set():
                    with contextlib.suppress(Exception):
                        await session.outgoing.put({"type": "ping", "at": int(time.time())})
        except asyncio.CancelledError:
            return

    async def _close_browser_resources(self) -> None:
        page, context, playwright = self._page, self._context, self._playwright
        self._page = None
        self._context = None
        self._playwright = None
        if page is not None:
            with contextlib.suppress(Exception):
                await page.close()
        if context is not None:
            with contextlib.suppress(Exception):
                await context.close()
        if playwright is not None:
            with contextlib.suppress(Exception):
                await playwright.stop()

    async def stop(self) -> None:
        self._stopped = True
        if self._maintenance_task:
            self._maintenance_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._maintenance_task
            self._maintenance_task = None
        await self._fail_pending(ProviderUnavailableError("Puter Web browser runtime stopped."))
        self._pending.clear()
        await self._close_browser_resources()
        if self._session:
            self._session.state = "stopped"
            self._session.connected.clear()
            self._session.ready.clear()

    async def begin_interactive_auth(self) -> Dict[str, Any]:
        """Open the one permitted visible browser sign-in flow.

        This only opens the local SDK bridge page and lets the user operate the
        documented Puter authentication UI.  No credentials/cookies are read by
        Python.  After success the persistent profile is reused headlessly.
        """
        await self.stop()
        self._stopped = False
        await self.start(wait_for_connection=True, headless=False)
        session = self._session
        if session is None:
            raise ProviderUnavailableError("Could not create Puter authentication session.")
        # The bridge page receives auth=1 and invokes documented SDK auth only
        # after the visible page has loaded.
        try:
            await self._page.goto(self.bridge_page_url(session, auth=True), wait_until="domcontentloaded")
        except Exception as exc:
            raise ProviderUnavailableError("Could not open the Puter authentication window.") from exc
        return {
            "ok": True,
            "message": "A Puter sign-in window was opened. Complete sign-in there; the local browser profile will be reused.",
            "profile_dir": str(self.profile_dir),
        }

    async def wait_for_authentication(self, timeout: Optional[int] = None) -> bool:
        deadline = time.monotonic() + float(timeout or self.options.get("auth_timeout") or 300)
        while time.monotonic() < deadline:
            session = self._session
            if session and session.authenticated is True:
                return True
            await asyncio.sleep(1)
        return False

    def status(self) -> Dict[str, Any]:
        session = self._session
        return {
            "enabled": self.definition.enabled,
            "state": session.state if session else "not_started",
            "connected": bool(session and session.connected.is_set()),
            "sdk_ready": bool(session and session.sdk_ready),
            "authenticated": bool(session and session.authenticated),
            "active_requests": len(self._pending),
            "active_background_sessions": 1 if session and session.connected.is_set() else 0,
            "profile_configured": bool(str(self.options.get("profile_dir") or "")),
            "headless": self.headless,
            "last_error": (session.last_error if session and session.last_error else self._last_error),
            "reconnect_count": self._reconnect_count,
        }

    # Test hook: makes mocked browser/Puter.js transport tests independent of a
    # real Playwright installation or Puter account.
    async def inject_event(self, request_id: str, event: Dict[str, Any]) -> None:
        pending = self._pending.get(request_id)
        if pending is None:
            raise ProviderProtocolError("Unknown Puter request id.")
        await pending.queue.put(dict(event))
