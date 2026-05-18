import httpx
import logging
import os
import time
import uuid
from pathlib import Path
from contextlib import asynccontextmanager
from collections import defaultdict
from typing import Callable, Awaitable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
import asyncio

from fastapi import FastAPI, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

from .logging_asyncio_filter import install_asyncio_noise_filter
from .utils.config import settings

install_asyncio_noise_filter()


class RequestIdFormatter(logging.Formatter):
    """Formatter that provides a default for request_id when not present."""

    def format(self, record: logging.LogRecord) -> str:
        if not hasattr(record, "request_id"):
            record.request_id = "-"
        return super().format(record)


_lvl = os.getenv("FREE_CODEX_LOG_LEVEL", "INFO").upper()
_handler = logging.StreamHandler()
_handler.setFormatter(
    RequestIdFormatter(
        fmt="%(asctime)s - %(name)s - [%(request_id)s] - %(levelname)s - %(message)s"
    )
)
logging.basicConfig(level=getattr(logging, _lvl, logging.INFO), handlers=[_handler])
logger = logging.getLogger("free-codex")


@dataclass
class RateLimitEntry:
    """Track request counts for rate limiting."""
    count: int = 0
    window_start: float = 0.0


class RateLimiter:
    """Simple in-memory rate limiter."""

    def __init__(
        self,
        requests_per_minute: int = 60,
        requests_per_hour: int = 1000,
    ):
        self.rpm = requests_per_minute
        self.rph = requests_per_hour
        self._minute_tracker: dict[str, RateLimitEntry] = defaultdict(
            lambda: RateLimitEntry(window_start=time.time())
        )
        self._hour_tracker: dict[str, RateLimitEntry] = defaultdict(
            lambda: RateLimitEntry(window_start=time.time())
        )
        self._lock = asyncio.Lock()

    async def is_allowed(self, client_id: str) -> tuple[bool, dict]:
        """Check if request is allowed. Returns (allowed, info)."""
        async with self._lock:
            now = time.time()
            info = {"limit": self.rpm, "remaining": 0, "reset": 0}

            # Check minute limit
            minute_entry = self._minute_tracker[client_id]
            if now - minute_entry.window_start > 60:
                minute_entry.count = 0
                minute_entry.window_start = now

            # Check hour limit
            hour_entry = self._hour_tracker[client_id]
            if now - hour_entry.window_start > 3600:
                hour_entry.count = 0
                hour_entry.window_start = now

            # Apply stricter limit
            if minute_entry.count >= self.rpm:
                reset = int(minute_entry.window_start + 60 - now)
                return False, {"limit": self.rpm, "remaining": 0, "reset": reset}

            if hour_entry.count >= self.rph:
                reset = int(hour_entry.window_start + 3600 - now)
                return False, {"limit": self.rph, "remaining": 0, "reset": reset}

            # Increment counters
            minute_entry.count += 1
            hour_entry.count += 1

            info = {
                "limit": self.rpm,
                "remaining": max(0, self.rpm - minute_entry.count),
                "reset": int(minute_entry.window_start + 60 - now),
            }
            return True, info

    def get_client_id(self, request: Request) -> str:
        """Extract client identifier from request."""
        # Try X-Forwarded-For first (for proxied requests)
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()

        # Try X-Real-IP
        real_ip = request.headers.get("x-real-ip")
        if real_ip:
            return real_ip

        # Fall back to client host
        if request.client:
            return request.client.host

        return "unknown"


# Create rate limiter instance
_rate_limiter = RateLimiter(
    requests_per_minute=int(os.getenv("FREE_CODEX_RATE_LIMIT_RPM", "60")),
    requests_per_hour=int(os.getenv("FREE_CODEX_RATE_LIMIT_RPH", "1000")),
)


def create_app() -> FastAPI:
    app_state: dict = {}

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        logger.info("Starting Free Codex server...")
        app.state.http_client = httpx.AsyncClient(
            timeout=httpx.Timeout(120.0, connect=10.0),
            limits=httpx.Limits(max_keepalive_connections=32, max_connections=100),
        )

        # Load cache on startup
        try:
            from .services.response_cache import response_cache
            await response_cache.load_from_disk()
            logger.info("Response cache loaded from disk")
        except Exception as e:
            logger.debug(f"Cache preload skipped: {e}")

        try:
            port = settings.server_port
        except Exception:
            port = 8080
        logger.info(f"Admin UI (local): http://127.0.0.1:{port}/admin")
        logger.info(f"Health Dashboard: http://127.0.0.1:{port}/health")
        yield

        # Cleanup
        try:
            from .services.response_cache import response_cache
            await response_cache.clear()
        except Exception:
            pass
        await app.state.http_client.aclose()
        logger.info("Stopped Free Codex server.")

    app = FastAPI(
        title="Free Codex",
        description="OpenAI-compatible API layer for Codex CLI and hosted models.",
        version="0.3.0",
        lifespan=lifespan
    )

    # CORS Middleware - Allow requests from any origin for development
    # In production, restrict this to your Codex installation
    cors_origins = os.getenv("FREE_CODEX_CORS_ORIGINS", "*").split(",")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID", "X-Response-Time"],
    )

    # Request tracking middleware
    @app.middleware("http")
    async def track_requests(request: Request, call_next: Callable) -> Response:
        # Generate or extract request ID
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        start_time = time.time()

        # Add request ID to app state for logging
        request.state.request_id = request_id

        # Rate limiting for API endpoints
        if request.url.path.startswith("/v1/") or request.url.path.startswith("/admin/api/"):
            client_id = _rate_limiter.get_client_id(request)
            allowed, rate_info = await _rate_limiter.is_allowed(client_id)

            if not allowed:
                logger.warning(f"Rate limit exceeded for {client_id}")
                return JSONResponse(
                    status_code=429,
                    headers={
                        "X-Request-ID": request_id,
                        "X-RateLimit-Limit": str(rate_info["limit"]),
                        "X-RateLimit-Remaining": "0",
                        "X-RateLimit-Reset": str(rate_info["reset"]),
                        "Retry-After": str(rate_info["reset"]),
                    },
                    content={
                        "error": {
                            "type": "rate_limit_exceeded",
                            "message": f"Rate limit exceeded. Try again in {rate_info['reset']} seconds.",
                            "limit": rate_info["limit"],
                            "retry_after": rate_info["reset"],
                        }
                    },
                )

        # Process request
        try:
            response = await call_next(request)

            # Add tracking headers
            response.headers["X-Request-ID"] = request_id
            response.headers["X-Response-Time"] = f"{(time.time() - start_time) * 1000:.1f}ms"

            # Add rate limit headers
            if request.url.path.startswith("/v1/"):
                client_id = _rate_limiter.get_client_id(request)
                _, rate_info = await _rate_limiter.is_allowed(client_id)
                response.headers["X-RateLimit-Limit"] = str(rate_info["limit"])
                response.headers["X-RateLimit-Remaining"] = str(rate_info["remaining"])
                response.headers["X-RateLimit-Reset"] = str(rate_info["reset"])

            # Log request
            if settings.access_log_requests:
                duration_ms = (time.time() - start_time) * 1000
                logger.info(
                    f"{request.method} {request.url.path} - {response.status_code} - {duration_ms:.1f}ms",
                    extra={"request_id": request_id}
                )

            return response

        except Exception as e:
            logger.error(
                f"Request failed: {str(e)}",
                extra={"request_id": request_id}
            )
            raise

    # Global exception handler
    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        request_id = getattr(request.state, "request_id", "unknown")

        if isinstance(exc, HTTPException):
            raise exc

        logger.error(
            f"Unhandled exception: {str(exc)}",
            exc_info=True,
            extra={"request_id": request_id}
        )

        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "message": "Internal Server Error",
                    "type": "server_error",
                    "code": "INTERNAL_ERROR",
                    "request_id": request_id,
                }
            },
            headers={"X-Request-ID": request_id},
        )

    # Include routers
    from .routes.admin import router as admin_router
    from .routes.admin_nim import router as admin_nim_router
    from .routes.chat import router as chat_router
    from .routes.models import router as models_router
    from .routes.responses import router as responses_router
    from .routes.embeddings import router as embeddings_router

    app.include_router(admin_router)
    app.include_router(admin_nim_router)
    app.include_router(chat_router, prefix="/v1")
    app.include_router(models_router, prefix="/v1")
    app.include_router(responses_router, prefix="/v1")
    app.include_router(embeddings_router)

    # Mount static files
    static_admin = Path(__file__).resolve().parent / "static" / "admin"
    app.mount(
        "/admin/static",
        StaticFiles(directory=str(static_admin)),
        name="admin_static",
    )

    static_root = Path(__file__).resolve().parent / "static"
    app.mount(
        "/static",
        StaticFiles(directory=str(static_root)),
        name="root_static",
    )

    # Health endpoints
    @app.get("/health", include_in_schema=False)
    async def health_page():
        """Serve the health/status dashboard page."""
        index = Path(__file__).resolve().parent / "static" / "index.html"
        from fastapi.responses import HTMLResponse
        return HTMLResponse(index.read_text(encoding="utf-8"))

    @app.get("/health/json")
    async def health_json(request: Request):
        """JSON health check with request tracking."""
        from .services.response_cache import response_cache

        request_id = getattr(request.state, "request_id", "unknown")

        return JSONResponse(
            content={
                "status": "healthy",
                "version": "0.3.0",
                "request_id": request_id,
                "cache": response_cache.get_stats(),
                "timestamp": datetime.utcnow().isoformat(),
            },
            headers={"X-Request-ID": request_id},
        )

    # System info endpoint
    @app.get("/v1/system")
    async def system_info(request: Request):
        """Get system information and capabilities."""
        request_id = getattr(request.state, "request_id", "unknown")

        return JSONResponse(
            content={
                "id": "free-codex",
                "version": "0.3.0",
                "capabilities": {
                    "streaming": True,
                    "tool_calling": True,
                    "thinking_models": True,
                    "embeddings": True,
                    "workspace_context": True,
                    "rate_limiting": True,
                    "caching": True,
                },
                "features": {
                    "retry_on_error": True,
                    "circuit_breaker": True,
                    "request_tracking": True,
                },
                "request_id": request_id,
            },
            headers={"X-Request-ID": request_id},
        )

    @app.get("/v1/auth/sentinel")
    @app.get("/auth/sentinel")
    async def auth_sentinel(request: Request):
        """Auth sentinel endpoint for Codex CLI and VS Code extension.

        Returns a valid auth response to confirm the API key is accepted.
        """
        return JSONResponse(
            content={
                "api_key": "accepted",
                "token_type": "Bearer",
            },
        )

    @app.post("/v1/auth/sentinel")
    @app.post("/auth/sentinel")
    async def auth_sentinel_post(request: Request):
        """Auth sentinel POST endpoint."""
        return JSONResponse(
            content={
                "api_key": "accepted",
                "token_type": "Bearer",
            },
        )

    @app.get("/v1/auth/session")
    @app.get("/auth/session")
    async def auth_session(request: Request):
        """Auth session endpoint for Codex VS Code extension."""
        scope = request.query_params.get("scope", "codex")
        return JSONResponse(
            content={
                "access_token": "freecodex_token",
                "token_type": "Bearer",
                "expires_in": 86400,
                "scope": scope,
            },
        )

    return app