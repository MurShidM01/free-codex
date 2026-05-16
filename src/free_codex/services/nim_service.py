"""NIM service with robust SSE streaming, retries, and thinking model support."""

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
    normalize_content_for_codex,
    strip_thinking_content,
)

logger = logging.getLogger("free-codex.nim")

# Configurable timeouts from environment (extended for thinking models)
READ_TIMEOUT = float(os.getenv("FREE_CODEX_READ_TIMEOUT", "300"))
CONNECT_TIMEOUT = float(os.getenv("FREE_CODEX_CONNECT_TIMEOUT", "30"))
MAX_RETRIES = int(os.getenv("FREE_CODEX_MAX_RETRIES", "3"))

# Thinking/reasoning models often need more time
THINKING_MODELS = {
    "deepseek", "qwen3", "qwq", "r1", "claude-sonnet-4",
    "step", "minimax", "gpt-o", "o1", "o3", "o4",
}


class NIMService:
    """Service for interacting with NVIDIA NIM / OpenAI-compatible API, including thinking/reasoning models."""

    def __init__(self, client: httpx.AsyncClient):
        self.client = client

    def _is_thinking_model(self, model: str) -> bool:
        """Check if model is a thinking/reasoning model that needs extended timeout."""
        model_lower = (model or "").lower()
        for tm in THINKING_MODELS:
            if tm in model_lower:
                return True
        return False

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

    def _timeout(self, extended: bool = False) -> httpx.Timeout:
        """Get timeout configuration. Use extended timeout for thinking models."""
        timeout = READ_TIMEOUT
        if extended:
            timeout = max(timeout, 600)  # At least 10 minutes for thinking models
        return httpx.Timeout(timeout, connect=CONNECT_TIMEOUT)

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

    async def _post_with_retry_extended(
        self,
        url: str,
        json: Dict[str, Any],
        headers: Dict[str, str],
        stream: bool = True,
        extended: bool = True,
    ) -> httpx.Response:
        """POST with extended timeout for thinking/reasoning models."""
        last_error = None
        # More retries for long-thinking models
        retries = max(MAX_RETRIES, 2)

        for attempt in range(retries + 1):
            try:
                timeout = self._timeout(extended=extended)
                if stream:
                    response = await self.client.stream(
                        "POST",
                        url,
                        json=json,
                        headers=headers,
                        timeout=timeout,
                    )
                else:
                    response = await self.client.post(
                        url,
                        json=json,
                        headers=headers,
                        timeout=timeout,
                    )
                # Success - check status code
                if 200 <= response.status_code < 300:
                    return response
                # Retry on certain status codes
                if response.status_code in (502, 503, 504, 429):
                    last_error = f"HTTP {response.status_code}"
                    if attempt < retries:
                        await asyncio.sleep(2 * (attempt + 1))  # Longer backoff for thinking models
                        continue
                return response
            except httpx.TimeoutException as e:
                last_error = f"Timeout after {timeout.connect_timeout}s: {e}"
                if attempt < retries:
                    await asyncio.sleep(2 * (attempt + 1))
                    continue
            except httpx.HTTPError as e:
                last_error = f"HTTP error: {e}"
                if attempt < retries:
                    await asyncio.sleep(2 * (attempt + 1))
                    continue
        raise httpx.HTTPError(f"Failed after {retries + 1} attempts: {last_error}")

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
        """Stream chat completion with robust error handling, extended timeouts for thinking models, and heartbeat."""
        payload = request.model_dump(exclude_none=True)
        payload = self._prepare_payload(payload)
        payload["stream"] = True

        model = self._get_actual_model(str(payload.get("model", "")))
        is_thinking = self._is_thinking_model(model)

        stream_payload = dict(payload)
        stream_payload["stream"] = True

        try:
            # Use extended timeout if this is a thinking/reasoning model
            timeout = self._timeout(extended=is_thinking)
            if is_thinking:
                logger.info(f"Using extended timeout ({timeout.connect_timeout}s) for thinking model: {model}")

            if is_thinking:
                # For thinking models: use heartbeat wrapper for long requests
                response = await self._post_with_retry_extended(
                    f"{settings.nim_base_url}/chat/completions",
                    json=stream_payload,
                    headers=self._auth_headers_sse(),
                    stream=True,
                    extended=is_thinking,
                )
            else:
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
                    f"NIM API returned {response.status_code}: {error_body[:200].decode('utf-8', errors='replace')}",
                    "upstream_error",
                )
                yield b"data: [DONE]\n\n"
                return

            # Stream with heartbeat for thinking models, usage tracking, and disconnect safety
            base_stream = track_usage_and_forward(sse_disconnect_safe(response.aiter_bytes()))

            if is_thinking:
                async for chunk in sse_with_heartbeat(base_stream, interval=25.0):
                    if chunk:
                        yield chunk
            else:
                async for chunk in base_stream:
                    if chunk:
                        yield chunk

            # Ensure we send [DONE] if not already present
            yield b"data: [DONE]\n\n"

        except httpx.TimeoutException as e:
            logger.error(f"NIM stream timeout: {e}")
            yield await yield_error_sse(
                "Request timed out. Thinking models may require more time. "
                "Try: FREE_CODEX_READ_TIMEOUT=600",
                "timeout"
            )
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