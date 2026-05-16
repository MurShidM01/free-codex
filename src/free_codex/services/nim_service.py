"""NIM service with robust SSE streaming support."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, AsyncGenerator, Dict

import httpx
from fastapi import HTTPException

from ..utils.config import settings
from ..models import ChatCompletionRequest, CompletionRequest
from .sse_utils import (
    sse_disconnect_safe,
    sse_with_heartbeat,
    yield_error_sse,
    track_usage_and_forward,
    usage_tracker,
)

logger = logging.getLogger("free-codex.nim")


class NIMService:
    """Service for interacting with NVIDIA NIM / OpenAI-compatible API."""

    def __init__(self, client: httpx.AsyncClient):
        self.client = client

    def _auth_headers(self) -> Dict[str, str]:
        """Get authentication headers for NIM requests."""
        return {
            "Authorization": f"Bearer {settings.nim_api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _get_actual_model(self, requested_model: str) -> str:
        """Resolve requested model to configured NIM model.

        Always use the configured NVIDIA_NIM_MODEL from settings.
        This allows config.toml to request any model name while
        ensuring we use the model configured in .env.
        """
        configured = settings.nim_model
        if not configured:
            raise HTTPException(
                status_code=500,
                detail="NVIDIA_NIM_MODEL not configured in .env",
            )
        return configured

    def _validate_response(self, response: httpx.Response) -> None:
        """Validate NIM response, raising HTTPException for errors."""
        if not (200 <= response.status_code < 300):
            raise HTTPException(
                status_code=response.status_code,
                detail=f"NIM API error: {response.text[:500]}",
            )

    async def get_chat_completion(self, request: ChatCompletionRequest) -> Dict[str, Any]:
        """Send a non-streaming chat completion request."""
        payload = request.model_dump(exclude_none=True)
        payload["model"] = self._get_actual_model(request.model)

        response = await self.client.post(
            f"{settings.nim_base_url}/chat/completions",
            json=payload,
            headers=self._auth_headers(),
        )

        self._validate_response(response)
        data = response.json()
        asyncio.create_task(usage_tracker.add_usage(data.get("usage", {})))
        return data

    async def stream_chat_completion(
        self, request: ChatCompletionRequest
    ) -> AsyncGenerator[bytes, None]:
        """Stream chat completion with robust error handling."""
        payload = request.model_dump(exclude_none=True)
        payload["model"] = self._get_actual_model(request.model)

        try:
            async with self.client.stream(
                "POST",
                f"{settings.nim_base_url}/chat/completions",
                json=payload,
                headers=self._auth_headers(),
                timeout=httpx.Timeout(120.0, connect=30.0),
            ) as response:
                if not (200 <= response.status_code < 300):
                    error_body = await response.aread()
                    logger.error(f"NIM stream error: {response.status_code} - {error_body[:200]}")
                    yield await yield_error_sse(
                        f"NIM API returned {response.status_code}",
                        "upstream_error",
                    )
                    yield b"data: [DONE]\n\n"
                    return

                # Stream the response with disconnect safety and usage tracking
                async for chunk in track_usage_and_forward(
                    sse_disconnect_safe(response.aiter_bytes())
                ):
                    if chunk:
                        yield chunk

                # Ensure we send [DONE] if not already present
                yield b"data: [DONE]\n\n"

        except httpx.TimeoutException as e:
            logger.error(f"NIM stream timeout: {e}")
            yield await yield_error_sse("Request timed out", "timeout")
            yield b"data: [DONE]\n\n"

        except httpx.HTTPError as e:
            logger.error(f"NIM HTTP error: {e}")
            yield await yield_error_sse(f"Connection error: {str(e)}", "connection_error")
            yield b"data: [DONE]\n\n"

        except Exception as e:
            logger.error(f"Unexpected stream error: {e}")
            yield await yield_error_sse(f"Stream error: {str(e)}", "stream_error")
            yield b"data: [DONE]\n\n"

    async def get_completion(self, request: CompletionRequest) -> Dict[str, Any]:
        """Send a non-streaming text completion request."""
        payload = request.model_dump(exclude_none=True)
        payload["model"] = self._get_actual_model(request.model)

        response = await self.client.post(
            f"{settings.nim_base_url}/completions",
            json=payload,
            headers=self._auth_headers(),
        )

        self._validate_response(response)
        data = response.json()
        asyncio.create_task(usage_tracker.add_usage(data.get("usage", {})))
        return data

    async def stream_completion(
        self, request: CompletionRequest
    ) -> AsyncGenerator[bytes, None]:
        """Stream text completion with robust error handling."""
        payload = request.model_dump(exclude_none=True)
        payload["model"] = self._get_actual_model(request.model)

        try:
            async with self.client.stream(
                "POST",
                f"{settings.nim_base_url}/completions",
                json=payload,
                headers=self._auth_headers(),
                timeout=httpx.Timeout(120.0, connect=30.0),
            ) as response:
                if not (200 <= response.status_code < 300):
                    error_body = await response.aread()
                    logger.error(f"NIM completion stream error: {response.status_code}")
                    yield await yield_error_sse(
                        f"NIM API returned {response.status_code}",
                        "upstream_error",
                    )
                    yield b"data: [DONE]\n\n"
                    return

                # Stream with disconnect safety and usage tracking
                async for chunk in track_usage_and_forward(
                    sse_disconnect_safe(response.aiter_bytes())
                ):
                    if chunk:
                        yield chunk

                yield b"data: [DONE]\n\n"

        except httpx.TimeoutException as e:
            logger.error(f"NIM completion stream timeout: {e}")
            yield await yield_error_sse("Request timed out", "timeout")
            yield b"data: [DONE]\n\n"

        except httpx.HTTPError as e:
            logger.error(f"NIM completion HTTP error: {e}")
            yield await yield_error_sse(f"Connection error: {str(e)}", "connection_error")
            yield b"data: [DONE]\n\n"

        except Exception as e:
            logger.error(f"Unexpected completion stream error: {e}")
            yield await yield_error_sse(f"Stream error: {str(e)}", "stream_error")
            yield b"data: [DONE]\n\n"

    async def post_chat_completions_payload(
        self, payload: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Send a chat completion with a raw payload dict."""
        p = dict(payload)
        p["model"] = self._get_actual_model(str(p.get("model", "")))
        p.pop("stream", None)

        response = await self.client.post(
            f"{settings.nim_base_url}/chat/completions",
            json=p,
            headers=self._auth_headers(),
        )

        self._validate_response(response)
        data = response.json()
        asyncio.create_task(usage_tracker.add_usage(data.get("usage", {})))
        return data

    async def stream_chat_completions_payload(
        self, payload: Dict[str, Any]
    ) -> AsyncGenerator[bytes, None]:
        """Stream from a raw payload dict."""
        p = dict(payload)
        p["model"] = self._get_actual_model(str(p.get("model", "")))
        p["stream"] = True

        try:
            async with self.client.stream(
                "POST",
                f"{settings.nim_base_url}/chat/completions",
                json=p,
                headers=self._auth_headers(),
                timeout=httpx.Timeout(120.0, connect=30.0),
            ) as response:
                if not (200 <= response.status_code < 300):
                    error_body = await response.aread()
                    logger.error(f"NIM payload stream error: {response.status_code}")
                    yield await yield_error_sse(
                        f"NIM API returned {response.status_code}",
                        "upstream_error",
                    )
                    yield b"data: [DONE]\n\n"
                    return

                # Stream with disconnect safety and usage tracking
                async for chunk in track_usage_and_forward(
                    sse_disconnect_safe(response.aiter_bytes())
                ):
                    if chunk:
                        yield chunk

                yield b"data: [DONE]\n\n"

        except httpx.TimeoutException as e:
            logger.error(f"NIM payload stream timeout: {e}")
            yield await yield_error_sse("Request timed out", "timeout")
            yield b"data: [DONE]\n\n"

        except httpx.HTTPError as e:
            logger.error(f"NIM payload stream HTTP error: {e}")
            yield await yield_error_sse(f"Connection error: {str(e)}", "connection_error")
            yield b"data: [DONE]\n\n"

        except Exception as e:
            logger.error(f"Unexpected payload stream error: {e}")
            yield await yield_error_sse(f"Stream error: {str(e)}", "stream_error")
            yield b"data: [DONE]\n\n"
