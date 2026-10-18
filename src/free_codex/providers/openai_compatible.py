"""OpenAI-compatible upstream provider transport.

NVIDIA NIM, Ollama, local vLLM/LM Studio and custom endpoints all share this
transport.  The router decides *which* provider/model to use before this code
runs, so requests are never globally forced to NVIDIA_NIM_MODEL.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, AsyncGenerator, Dict, List, Optional

import httpx

from ..services.chat_payload import normalize_chat_payload
from ..utils.config import ProviderDefinition, ProviderType, Settings
from .base import (
    Provider,
    ProviderCapabilities,
    ProviderError,
    ProviderHealth,
    ProviderModel,
    ProviderProtocolError,
    ProviderUnavailableError,
)

logger = logging.getLogger("free-codex.providers.openai")


class OpenAICompatibleProvider(Provider):
    """A cautious transport for documented OpenAI-compatible endpoints."""

    provider_type = "custom_openai"

    def __init__(
        self,
        definition: ProviderDefinition,
        *,
        client: Optional[httpx.AsyncClient],
        settings: Settings,
    ) -> None:
        capabilities = ProviderCapabilities.from_mapping(definition.capabilities)
        super().__init__(
            definition.id,
            default_model=definition.default_model,
            enabled=definition.enabled,
            capabilities=capabilities,
        )
        self.definition = definition
        self.client = client
        self.settings = settings
        self.provider_type = definition.type.value
        self._semaphore: Optional[asyncio.Semaphore] = None
        if definition.max_concurrent_requests > 0:
            self._semaphore = asyncio.Semaphore(definition.max_concurrent_requests)

    @property
    def base_url(self) -> str:
        return self.definition.base_url.rstrip("/")

    def resolve_model(self, requested_model: str) -> str:
        return self.definition.resolve_model(requested_model)

    def capabilities_for_model(self, model: str) -> ProviderCapabilities:
        return ProviderCapabilities.from_mapping(
            self.definition.capabilities_for_model(model), self.capabilities
        )

    def model_metadata(self, model: Optional[str] = None) -> ProviderModel:
        metadata = super().model_metadata(model)
        target = metadata.id
        metadata.aliases = [
            alias for alias, value in self.definition.model_aliases.items() if value == target
        ]
        return metadata

    def _ensure_available(self) -> None:
        if not self.enabled:
            raise ProviderUnavailableError("Provider '{0}' is disabled.".format(self.id))
        if not self.base_url:
            raise ProviderUnavailableError(
                "Provider '{0}' is not configured with a base URL.".format(self.id)
            )
        if self.client is None:
            raise ProviderUnavailableError("Provider transport is not initialized yet.")

    def _headers(self, stream: bool = False) -> Dict[str, str]:
        headers = {"Content-Type": "application/json", "Accept": "text/event-stream" if stream else "application/json"}
        api_key = self.definition.resolve_api_key()
        if api_key:
            headers["Authorization"] = "Bearer {0}".format(api_key)
        return headers

    def _timeout(self, model: str = "") -> httpx.Timeout:
        # Retain long timeout behavior for known thinking model names, without
        # assuming a provider has a reasoning capability.
        thinking_terms = ("deepseek", "qwen3", "qwq", "-r1", "/r1", "o1", "o3", "o4")
        extended = any(term in (model or "").lower() for term in thinking_terms)
        read = max(self.settings.read_timeout, 600) if extended else self.settings.read_timeout
        return httpx.Timeout(read, connect=self.settings.connect_timeout)

    def _prepare_chat_payload(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        result = dict(payload)
        model = self.resolve_model(str(result.get("model") or ""))
        if not model:
            raise ProviderError(
                "No model was selected for provider '{0}'. Configure a default model or send model=.".format(self.id),
                status_code=400,
                error_type="model_not_configured",
            )
        result["model"] = model
        normalize_chat_payload(result)
        return result

    def _prepare_completion_payload(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        result = dict(payload)
        model = self.resolve_model(str(result.get("model") or ""))
        if not model:
            raise ProviderError(
                "No model was selected for provider '{0}'.".format(self.id),
                status_code=400,
                error_type="model_not_configured",
            )
        result["model"] = model
        return {key: value for key, value in result.items() if value is not None}

    def _url(self, path: str) -> str:
        return "{0}/{1}".format(self.base_url, path.lstrip("/"))

    @staticmethod
    def _provider_error_from_response(response: httpx.Response) -> ProviderError:
        status = response.status_code
        retryable = status in (408, 409, 429, 500, 502, 503, 504)
        if status in (401, 403):
            msg = "Provider authentication was rejected. Check its configured credentials."
            etype = "provider_authentication_error"
        elif status == 404:
            msg = "Provider endpoint or selected model was not found."
            etype = "provider_not_found"
        elif status == 429:
            msg = "Provider rate limit reached."
            etype = "provider_rate_limited"
        else:
            msg = "Provider returned HTTP {0}.".format(status)
            etype = "provider_http_error"
        if status in (502, 503, 504):
            return ProviderUnavailableError(msg, status_code=status, error_type=etype, retryable=True)
        return ProviderError(msg, status_code=status, error_type=etype, retryable=retryable)

    async def _post_json(self, path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        self._ensure_available()
        assert self.client is not None
        retries = max(0, self.settings.max_retries)
        last_error: Optional[Exception] = None
        for attempt in range(retries + 1):
            try:
                async with self._slot():
                    response = await self.client.post(
                        self._url(path),
                        json=payload,
                        headers=self._headers(),
                        timeout=self._timeout(str(payload.get("model") or "")),
                    )
                if 200 <= response.status_code < 300:
                    try:
                        data = response.json()
                    except ValueError as exc:
                        raise ProviderProtocolError("Provider returned invalid JSON.") from exc
                    if not isinstance(data, dict):
                        raise ProviderProtocolError("Provider returned an unexpected JSON payload.")
                    return data
                err = self._provider_error_from_response(response)
                if err.retryable and attempt < retries:
                    await asyncio.sleep(min(4.0, 0.5 * (2 ** attempt)))
                    continue
                raise err
            except ProviderError:
                raise
            except (httpx.TimeoutException, httpx.NetworkError, httpx.HTTPError) as exc:
                last_error = exc
                if attempt < retries:
                    await asyncio.sleep(min(4.0, 0.5 * (2 ** attempt)))
                    continue
                raise ProviderUnavailableError(
                    "Provider '{0}' could not be reached.".format(self.id)
                ) from exc
        raise ProviderUnavailableError("Provider request failed after retries.") from last_error

    class _NullSlot:
        async def __aenter__(self) -> None:
            return None

        async def __aexit__(self, *args: Any) -> None:
            return None

    def _slot(self) -> Any:
        return self._semaphore if self._semaphore is not None else self._NullSlot()

    async def chat_completion(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        prepared = self._prepare_chat_payload(payload)
        prepared.pop("stream", None)
        return await self._post_json("chat/completions", prepared)

    async def stream_chat_completion(self, payload: Dict[str, Any]) -> AsyncGenerator[bytes, None]:
        prepared = self._prepare_chat_payload(payload)
        prepared["stream"] = True
        self._ensure_available()
        assert self.client is not None
        retries = max(0, self.settings.max_retries)
        cm: Any = None
        response: Optional[httpx.Response] = None
        slot = self._slot()
        await slot.__aenter__()
        try:
            for attempt in range(retries + 1):
                try:
                    cm = self.client.stream(
                        "POST",
                        self._url("chat/completions"),
                        json=prepared,
                        headers=self._headers(stream=True),
                        timeout=self._timeout(str(prepared.get("model") or "")),
                    )
                    response = await cm.__aenter__()
                    if 200 <= response.status_code < 300:
                        break
                    err = self._provider_error_from_response(response)
                    await cm.__aexit__(None, None, None)
                    cm = None
                    if err.retryable and attempt < retries:
                        await asyncio.sleep(min(4.0, 0.5 * (2 ** attempt)))
                        continue
                    raise err
                except ProviderError:
                    raise
                except (httpx.TimeoutException, httpx.NetworkError, httpx.HTTPError) as exc:
                    if cm is not None:
                        try:
                            await cm.__aexit__(None, None, None)
                        except Exception:
                            pass
                        cm = None
                    if attempt < retries:
                        await asyncio.sleep(min(4.0, 0.5 * (2 ** attempt)))
                        continue
                    raise ProviderUnavailableError(
                        "Provider '{0}' could not start a streaming request.".format(self.id)
                    ) from exc
            if response is None:
                raise ProviderUnavailableError("Provider did not start a response stream.")
            async for chunk in response.aiter_bytes():
                if chunk:
                    yield chunk
        finally:
            if cm is not None:
                try:
                    await cm.__aexit__(None, None, None)
                except Exception:
                    logger.debug("stream cleanup failed", exc_info=True)
            await slot.__aexit__(None, None, None)

    async def completion(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        prepared = self._prepare_completion_payload(payload)
        prepared.pop("stream", None)
        return await self._post_json("completions", prepared)

    async def stream_completion(self, payload: Dict[str, Any]) -> AsyncGenerator[bytes, None]:
        prepared = self._prepare_completion_payload(payload)
        prepared["stream"] = True
        # Reuse the same safe transport pattern but not chat normalization.
        self._ensure_available()
        assert self.client is not None
        cm: Any = None
        slot = self._slot()
        await slot.__aenter__()
        try:
            cm = self.client.stream(
                "POST",
                self._url("completions"),
                json=prepared,
                headers=self._headers(stream=True),
                timeout=self._timeout(str(prepared.get("model") or "")),
            )
            response = await cm.__aenter__()
            if not (200 <= response.status_code < 300):
                raise self._provider_error_from_response(response)
            async for chunk in response.aiter_bytes():
                if chunk:
                    yield chunk
        except (httpx.TimeoutException, httpx.NetworkError, httpx.HTTPError) as exc:
            raise ProviderUnavailableError(
                "Provider '{0}' could not start a completion stream.".format(self.id)
            ) from exc
        finally:
            if cm is not None:
                try:
                    await cm.__aexit__(None, None, None)
                except Exception:
                    pass
            await slot.__aexit__(None, None, None)

    async def list_models(self) -> List[ProviderModel]:
        fallback = [self.model_metadata()] if self.default_model else []
        if not self.enabled or not self.base_url or self.client is None:
            return fallback
        try:
            response = await self.client.get(
                self._url("models"), headers=self._headers(), timeout=httpx.Timeout(10, connect=5)
            )
            if not (200 <= response.status_code < 300):
                return fallback
            data = response.json()
            models = data.get("data", []) if isinstance(data, dict) else []
            result: List[ProviderModel] = []
            for item in models:
                mid = item.get("id") if isinstance(item, dict) else None
                if isinstance(mid, str) and mid:
                    result.append(
                        ProviderModel(
                            id=mid,
                            provider=self.id,
                            capabilities=self.capabilities_for_model(mid),
                            owned_by=self.provider_type,
                            ready=True,
                        )
                    )
            return result or fallback
        except (httpx.HTTPError, ValueError):
            return fallback

    async def health(self, *, probe: bool = False) -> ProviderHealth:
        requires_key = self.definition.type == ProviderType.NVIDIA_NIM
        configured = bool(self.base_url) and (not requires_key or bool(self.definition.resolve_api_key()))
        if not self.enabled:
            return ProviderHealth(self.id, configured=configured, ready=False, status="disabled")
        if not configured:
            message = "Missing base URL."
            if self.base_url and requires_key:
                message = "Missing NVIDIA NIM API key."
            return ProviderHealth(
                self.id, configured=False, ready=False, status="not_configured", message=message
            )
        if not probe or self.client is None:
            return ProviderHealth(self.id, configured=True, ready=True, status="configured")
        start = time.monotonic()
        try:
            response = await self.client.get(
                self._url("models"), headers=self._headers(), timeout=httpx.Timeout(8, connect=4)
            )
            ready = 200 <= response.status_code < 500
            return ProviderHealth(
                self.id,
                configured=True,
                ready=ready,
                status="ready" if ready else "unreachable",
                message="" if ready else "Provider returned HTTP {0}.".format(response.status_code),
                details={"latency_ms": round((time.monotonic() - start) * 1000, 1)},
            )
        except httpx.HTTPError:
            return ProviderHealth(
                self.id, configured=True, ready=False, status="unreachable", message="Provider could not be reached."
            )


class NvidiaNIMProvider(OpenAICompatibleProvider):
    """Named subclass retained for diagnostics and backwards compatibility."""

    provider_type = ProviderType.NVIDIA_NIM.value


class OllamaProvider(OpenAICompatibleProvider):
    provider_type = ProviderType.OLLAMA.value


class LocalProvider(OpenAICompatibleProvider):
    provider_type = ProviderType.LOCAL.value


class CustomOpenAIProvider(OpenAICompatibleProvider):
    provider_type = ProviderType.CUSTOM_OPENAI.value
