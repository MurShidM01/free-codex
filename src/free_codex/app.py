import httpx
import logging
import os
from pathlib import Path

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from .logging_asyncio_filter import install_asyncio_noise_filter
from .utils.config import settings

install_asyncio_noise_filter()

_lvl = os.getenv("FREE_CODEX_LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, _lvl, logging.INFO),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("free-codex")

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting Free Codex server…")
    app.state.http_client = httpx.AsyncClient(
        timeout=httpx.Timeout(120.0, connect=10.0),
        limits=httpx.Limits(max_keepalive_connections=32, max_connections=100),
    )
    try:
        port = settings.server_port
    except Exception:
        port = 8080
    logger.info(f"Admin UI (local): http://127.0.0.1:{port}/admin")
    yield
    await app.state.http_client.aclose()
    logger.info("Stopped Free Codex server.")

def create_app() -> FastAPI:
    app = FastAPI(
        title="Free Codex",
        description="OpenAI-compatible API layer for Codex CLI and hosted models.",
        version="0.1.0",
        lifespan=lifespan
    )
    
    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        if isinstance(exc, HTTPException):
            raise exc
        logger.error(f"Unhandled exception: {str(exc)}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "message": "Internal Server Error",
                    "type": "server_error",
                    "detail": str(exc),
                }
            },
        )

    @app.middleware("http")
    async def log_requests(request: Request, call_next):
        if settings.access_log_requests:
            logger.info(f"Incoming request: {request.method} {request.url}")
        response = await call_next(request)
        if settings.access_log_requests:
            logger.info(f"Response status: {response.status_code}")
        return response

    from .routes.admin import router as admin_router
    from .routes.admin_nim import router as admin_nim_router
    from .routes.chat import router as chat_router
    from .routes.models import router as models_router
    from .routes.responses import router as responses_router

    app.include_router(admin_router)
    app.include_router(admin_nim_router)
    app.include_router(chat_router, prefix="/v1")
    app.include_router(models_router, prefix="/v1")
    app.include_router(responses_router, prefix="/v1")

    static_admin = Path(__file__).resolve().parent / "static" / "admin"
    app.mount(
        "/admin/static",
        StaticFiles(directory=str(static_admin)),
        name="admin_static",
    )

    @app.get("/health")
    async def health_check():
        return {"status": "healthy"}
        
    return app
