"""NIM service with robust SSE streaming, retries, and extended model support."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any, AsyncGenerator, Dict, Optional

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

# Configurable timeouts from environment
READ_TIMEOUT = float(os.getenv("FREE_CODEX_READ_TIMEOUT", "180"))
CONNECT_TIMEOUT = float(os.getenv("FREE_CODEX_CONNECT_TIMEOUT", "30"))
MAX_RETRIES = int(os.getenv("FREE_CODEX_MAX_RETRIES", "2"))


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

    def _auth_headers_sse(self) -> Dict[str, str]:
        """Get headers for SSE streaming with longer timeout."""
        headers = self._auth_headers()
        headers["Accept"] = "text/event-stream"
        return headers

    def _timeout(self) -> httpx.Timeout:
        """Get timeout configuration."""
        return httpx.Timeout(READ_TIMEOUT, connect=CONNECT_TIMEOUT)

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

    async def _post_with_retry(
        self,
        url: str,
        json: Dict[str, Any],
        headers: Dict[str, str],
        stream: bool = False,
    ) -> httpx.Response:
        """POST with automatic retry on transient errors."""
        last_error = None
        for attempt in range(MAX_RETRIES + 1):
            try:
                if stream:
                    response = await self.client.stream(
                        "POST",
                        url,
                        json=json,
                        headers=headers,
                        timeout=self._timeout(),
                    )
                else:
                    response = await self.client.post(
                        url,
                        json=json,
                        headers=headers,
                        timeout=self._timeout(),
                    )
                # Success - check status code
                if 200 <= response.status_code < 300:
                    return response
                # Retry on certain status codes
                if response.status_code in (502, 503, 504, 429):
                    last_error = f"HTTP {response.status_code}"
                    if attempt < MAX_RETRIES:
                        await asyncio.sleep(1 * (attempt + 1))  # Exponential backoff
                        continue
                return response
            except httpx.TimeoutException as e:
                last_error = f"Timeout: {e}"
                if attempt < MAX_RETRIES:
                    await asyncio.sleep(1 * (attempt + 1))
                    continue
            except httpx.HTTPError as e:
                last_error = f"HTTP error: {e}"
                if attempt < MAX_RETRIES:
                    await asyncio.sleep(1 * (attempt + 1))
                    continue
        raise httpx.HTTPError(f"Failed after {MAX_RETRIES + 1} attempts: {last_error}")

    def _prepare_payload(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Prepare payload with model override and optional extended parameters."""
        # Always use configured model
        payload["model"] = self._get_actual_model(str(payload.get("model", "")))

        # Copy extended parameters if present and not None
        extended_params = ["seed", "reasoning_effort", "thinking", "metadata"]
        for param in extended_params:
            if param in payload and payload[param] is not None:
                pass  # Keep the parameter as-is
            elif param in ["seed", "reasoning_effort"] and param in payload:
                # These should only be passed if explicitly set
                if payload.get(param) is None:
                    payload.pop(param, None)

        # Remove non-standard parameters to avoid NIM errors
        standard_params = {
            "model", "messages", "temperature", "top_p", "n", "stream",
            "stop", "max_tokens", "presence_penalty", "frequency_penalty",
            "logit_bias", "user", "tools", "tool_choice", "functions",
            "function_call", "seed", "response_format", "tools",
        }
        payload = {k: v for k, v in payload.items() if k in standard_params or v is not None}

        return payload

    async def get_chat_completion(self, request: ChatCompletionRequest) -> Dict[str, Any]:
        """Send a non-streaming chat completion request with retry support."""
        payload = request.model_dump(exclude_none=True)
        payload = self._prepare_payload(payload)
        payload.pop("stream", None)

        response = await self._post_with_retry(
            f"{settings.nim_base_url}/chat/completions",
            json=payload,
            headers=self._auth_headers(),
            stream=False,
        )

        self._validate_response(response)
        data = response.json()
        asyncio.create_task(usage_tracker.add_usage(data.get("usage", {})))
        return data

    async def stream_chat_completion(
        self, request: ChatCompletionRequest
    ) -> AsyncGenerator[bytes, None]:
        """Stream chat completion with robust error handling and retries."""
        payload = request.model_dump(exclude_none=True)
        payload = self._prepare_payload(payload)
        payload["stream"] = True

        stream_payload = dict(payload)
        stream_payload["stream"] = True

        try:
            response = await self._post_with_retry(
                f"{settings.nim_base_url}/chat/completions",
                json=stream_payload,
                headers=self._auth_headers_sse(),
                stream=True,
            )

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
            yield await yield_error_sse("Request timed out. Try increasing FREE_CODEX_READ_TIMEOUT.", "timeout")
            yield b"data: [DONE]\n\n"

        except httpx.HTTPError as e:
            logger.error(f"NIM HTTP error: {e}")
            yield await yield_error_sse(f"Connection error: {str(e)}. Check your API endpoint.", "connection_error")
            yield b"data: [DONE]\n\n"

        except Exception as e:
            logger.error(f"Unexpected stream error: {e}")
            yield await yield_error_sse(f"Stream error: {str(e)}", "stream_error")
            yield b"data: [DONE]\n\n"

    async def get_completion(self, request: CompletionRequest) -> Dict[str, Any]:
        """Send a non-streaming text completion request."""
        payload = request.model_dump(exclude_none=True)
        payload = self._prepare_payload(payload)
        payload.pop("stream", None)

        response = await self._post_with_retry(
            f"{settings.nim_base_url}/completions",
            json=payload,
            headers=self._auth_headers(),
            stream=False,
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
        payload = self._prepare_payload(payload)
        payload["stream"] = True

        stream_payload = dict(payload)
        stream_payload["stream"] = True

        try:
            response = await self._post_with_retry(
                f"{settings.nim_base_url}/completions",
                json=stream_payload,
                headers=self._auth_headers_sse(),
                stream=True,
            )

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
            yield await yield_error_sse("Request timed out. Try increasing FREE_CODEX_READ_TIMEOUT.", "timeout")
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
        p = self._prepare_payload(dict(payload))
        p.pop("stream", None)

        response = await self._post_with_retry(
            f"{settings.nim_base_url}/chat/completions",
            json=p,
            headers=self._auth_headers(),
            stream=False,
        )

        self._validate_response(response)
        data = response.json()
        asyncio.create_task(usage_tracker.add_usage(data.get("usage", {})))
        return data

    async def stream_chat_completions_payload(
        self, payload: Dict[str, Any]
    ) -> AsyncGenerator[bytes, None]:
        """Stream from a raw payload dict with retries."""
        p = self._prepare_payload(dict(payload))
        p["stream"] = True

        try:
            response = await self._post_with_retry(
                f"{settings.nim_base_url}/chat/completions",
                json=p,
                headers=self._auth_headers_sse(),
                stream=True,
            )

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