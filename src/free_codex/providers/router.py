"""First-class provider registry and request router for the local proxy."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any, AsyncGenerator, Dict, List, Optional, Tuple

import httpx

from ..services.provider_logging import ProviderEventLogger
from ..utils.config import ProviderDefinition, ProviderType, Settings
from .base import (
    Provider,
    ProviderCapabilities,
    ProviderError,
    ProviderHealth,
    ProviderNotFoundError,
    ProviderUnavailableError,
    UnsupportedCapabilityError,
)
from .openai_compatible import (
    CustomOpenAIProvider,
    LocalProvider,
    NvidiaNIMProvider,
    OllamaProvider,
)
from .puter_web import PuterWebProvider

logger = logging.getLogger("free-codex.providers.router")


@dataclass
class ProviderSelection:
    provider_id: str
    provider: Provider
    model: str
    requested_model: str
    source: str
    fallback_provider_ids: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "provider": self.provider_id,
            "model": self.model,
            "requested_model": self.requested_model,
            "source": self.source,
            "fallback_providers": list(self.fallback_provider_ids),
        }


class ProviderRouter:
    """Resolve local requests to provider transports without exposing them to Codex."""

    _ID_ALIASES = {
        "nvidia": "nvidia",
        "nvidia_nim": "nvidia",
        "nim": "nvidia",
        "ollama": "ollama",
        "local": "local",
        "custom": "custom_openai",
        "custom_openai": "custom_openai",
        "openai": "custom_openai",
        "puter": "puter_web",
        "puter_web": "puter_web",
        "puter-web": "puter_web",
    }

    def __init__(
        self,
        settings: Settings,
        client: Optional[httpx.AsyncClient] = None,
        *,
        bridge_base_url: str = "",
    ) -> None:
        self.settings = settings
        self.client = client
        self.bridge_base_url = bridge_base_url
        self.event_logger = ProviderEventLogger(debug=settings.debug_provider_payloads)
        self.providers: Dict[str, Provider] = {}
        self._response_sticky: Dict[str, Tuple[str, str, float]] = {}
        self._lock = asyncio.Lock()
        self._build_providers()

    def _build_providers(self) -> None:
        self.providers.clear()
        for provider_id, definition in self.settings.provider_definitions.items():
            self.providers[provider_id] = self._make_provider(definition)

    def _make_provider(self, definition: ProviderDefinition) -> Provider:
        kwargs = {"client": self.client, "settings": self.settings}
        if definition.type == ProviderType.NVIDIA_NIM:
            return NvidiaNIMProvider(definition, **kwargs)
        if definition.type == ProviderType.OLLAMA:
            return OllamaProvider(definition, **kwargs)
        if definition.type == ProviderType.LOCAL:
            return LocalProvider(definition, **kwargs)
        if definition.type == ProviderType.PUTER_WEB:
            provider = PuterWebProvider(definition, event_logger=self.event_logger)
            if self.bridge_base_url:
                provider.manager.set_bridge_base_url(self.bridge_base_url)
            return provider
        return CustomOpenAIProvider(definition, **kwargs)

    def attach_client(self, client: httpx.AsyncClient) -> None:
        self.client = client
        for provider in self.providers.values():
            if hasattr(provider, "client"):
                provider.client = client  # type: ignore[attr-defined]

    def set_bridge_base_url(self, value: str) -> None:
        self.bridge_base_url = value.rstrip("/")
        manager = self.puter_browser_manager
        if manager is not None:
            manager.set_bridge_base_url(self.bridge_base_url)

    @property
    def puter_browser_manager(self):
        for provider in self.providers.values():
            if isinstance(provider, PuterWebProvider):
                return provider.manager
        return None

    async def reload_configuration(self) -> None:
        """Rebuild provider instances after a deliberate config reload."""
        async with self._lock:
            for provider in self.providers.values():
                await provider.stop()
            self._build_providers()
            if self.client:
                self.attach_client(self.client)
            if self.bridge_base_url:
                self.set_bridge_base_url(self.bridge_base_url)
            self._response_sticky.clear()

    async def start(self) -> None:
        # Browser startup is on-demand by default. An explicit auto-start is
        # useful for service deployments and causes a clear auth state in health.
        default = self._canonical_provider_id(self.settings.default_provider)
        auto_start = str(__import__("os").environ.get("PUTER_WEB_AUTO_START", "")).lower() in ("1", "true", "yes", "on")
        provider = self.providers.get(default)
        if isinstance(provider, PuterWebProvider) and provider.enabled and (auto_start or default == "puter_web"):
            try:
                await provider.start()
            except ProviderError as exc:
                # Existing providers must still start if Playwright/auth is not
                # ready; the request path returns an actionable provider error.
                self.event_logger.event("browser_start_error", provider=provider.id, status="unavailable", error_type=exc.error_type)
            except Exception:
                # Never make an optional browser provider prevent NVIDIA,
                # Ollama, or custom transports from starting.
                self.event_logger.event("browser_start_error", provider=provider.id, status="unavailable", error_type="browser_start_error")

    async def stop(self) -> None:
        for provider in list(self.providers.values()):
            try:
                await provider.stop()
            except Exception:
                logger.debug("provider shutdown failed", exc_info=True)
        self._response_sticky.clear()

    @classmethod
    def _canonical_provider_id(cls, value: str) -> str:
        raw = (value or "").strip().lower().replace(" ", "_")
        return cls._ID_ALIASES.get(raw, raw.replace("-", "_"))

    def get_provider(self, provider_id: str) -> Provider:
        canonical = self._canonical_provider_id(provider_id)
        provider = self.providers.get(canonical)
        if provider is None:
            raise ProviderNotFoundError("Provider '{0}' is not configured.".format(provider_id))
        return provider

    def _split_route_target(self, target: str) -> Tuple[str, str]:
        target = (target or "").strip()
        if not target:
            return "", ""
        # ``provider::model`` is unambiguous for model IDs that themselves
        # contain `/`; ``provider:model`` is supported for CLI convenience.
        for separator in ("::", ":"):
            if separator in target:
                provider, model = target.split(separator, 1)
                canonical = self._canonical_provider_id(provider)
                if canonical in self.providers:
                    return canonical, model
        # Support a provider/model prefix only when it names a configured
        # provider. Raw model IDs such as deepseek/foo remain untouched.
        if "/" in target:
            provider, model = target.split("/", 1)
            canonical = self._canonical_provider_id(provider)
            if canonical in self.providers:
                return canonical, model
        canonical = self._canonical_provider_id(target)
        if canonical in self.providers:
            return canonical, ""
        return "", target

    def _explicit_provider(self, body: Dict[str, Any], headers: Optional[Dict[str, str]]) -> str:
        value = body.get("provider")
        if isinstance(value, str) and value.strip():
            return value.strip()
        metadata = body.get("metadata")
        if isinstance(metadata, dict):
            for key in ("free_codex_provider", "provider"):
                value = metadata.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
        if headers:
            value = headers.get("x-free-codex-provider") or headers.get("X-Free-Codex-Provider")
            if value:
                return value.strip()
        return ""

    def select(
        self,
        *,
        body: Dict[str, Any],
        requested_model: str,
        headers: Optional[Dict[str, str]] = None,
    ) -> ProviderSelection:
        requested = (requested_model or "").strip()
        sticky_id = body.get("previous_response_id")
        if self.settings.routing.sticky_sessions and isinstance(sticky_id, str):
            sticky = self._response_sticky.get(sticky_id)
            if sticky and sticky[2] > time.monotonic():
                provider = self.get_provider(sticky[0])
                return ProviderSelection(sticky[0], provider, sticky[1], requested, "sticky", [])

        explicit = self._explicit_provider(body, headers)
        provider_id = ""
        model = requested
        source = "default"
        if explicit:
            provider_id = self._canonical_provider_id(explicit)
            source = "explicit"
        else:
            # Config aliases are resolved before model-route patterns.
            alias_target = self.settings.routing.aliases.get(requested)
            if alias_target:
                provider_id, mapped_model = self._split_route_target(alias_target)
                model = mapped_model or requested
                source = "alias"
            if not provider_id:
                route_target = self.settings.routing.model_routes.get(requested)
                if route_target:
                    provider_id, mapped_model = self._split_route_target(route_target)
                    model = mapped_model or requested
                    source = "route"
            if not provider_id:
                prefixed_provider, prefixed_model = self._split_route_target(requested)
                if prefixed_provider:
                    provider_id, model, source = prefixed_provider, prefixed_model, "model_prefix"
        if not provider_id:
            provider_id = self._canonical_provider_id(self.settings.default_provider)
        provider = self.get_provider(provider_id)
        if not provider.enabled:
            raise ProviderUnavailableError("Provider '{0}' is disabled.".format(provider_id))
        # Legacy aliases mean "use configured NIM model", not a literal model.
        if model in ("", "nvidia_nim", "nvidia", "default", "auto"):
            model = provider.default_model
        # Preserve legacy NIM behavior: generic Codex compatibility model names
        # (gpt-4, nvidia_nim, etc.) resolve to NVIDIA_NIM_MODEL unless the user
        # explicitly configured a model route or used an `nvidia:model` prefix.
        if (
            getattr(provider, "provider_type", "") == ProviderType.NVIDIA_NIM.value
            and source in ("default", "explicit")
            and provider.default_model
            and requested != provider.default_model
        ):
            model = provider.default_model
        # Provider-local aliases may be written as `puter/foo` while model
        # prefix parsing has already stripped `puter/`.
        definition = getattr(provider, "definition", None)
        if definition is not None and requested in getattr(definition, "model_aliases", {}):
            model = definition.model_aliases[requested]
        resolved = provider.resolve_model(model)
        if not resolved:
            raise ProviderError(
                "No model selected for provider '{0}'. Set a default model, route alias, or request model.".format(provider_id),
                status_code=400,
                error_type="model_not_configured",
            )
        fallback = []
        wants_fallback = bool(body.get("free_codex_fallback"))
        metadata = body.get("metadata")
        if isinstance(metadata, dict):
            wants_fallback = wants_fallback or bool(metadata.get("free_codex_fallback"))
        # Never switch an active tool-result turn unless expressly requested;
        # provider/model consistency is essential for call IDs and context.
        has_tool_result = self._payload_has_tool_result(body)
        if wants_fallback and not has_tool_result:
            fallback = [
                self._canonical_provider_id(item)
                for item in self.settings.routing.fallback_providers
                if self._canonical_provider_id(item) != provider_id
            ]
        selection = ProviderSelection(provider_id, provider, resolved, requested, source, fallback)
        self.validate_capabilities(selection, body)
        return selection

    @staticmethod
    def _payload_has_tool_result(payload: Dict[str, Any]) -> bool:
        input_value = payload.get("input")
        if isinstance(input_value, list):
            for item in input_value:
                if isinstance(item, dict) and item.get("type") in ("function_call_output", "tool_result"):
                    return True
        messages = payload.get("messages")
        return bool(isinstance(messages, list) and any(isinstance(item, dict) and item.get("role") == "tool" for item in messages))

    @staticmethod
    def _contains_media(value: Any) -> Tuple[bool, bool]:
        image = False
        video = False
        if isinstance(value, dict):
            kind = str(value.get("type") or "").lower()
            if kind in ("input_image", "image", "image_url") or "image_url" in value:
                image = True
            if kind in ("input_video", "video", "video_url") or "video_url" in value:
                video = True
            for item in value.values():
                i, v = ProviderRouter._contains_media(item)
                image = image or i
                video = video or v
        elif isinstance(value, list):
            for item in value:
                i, v = ProviderRouter._contains_media(item)
                image = image or i
                video = video or v
        return image, video

    def validate_capabilities(self, selection: ProviderSelection, body: Dict[str, Any]) -> None:
        caps = selection.provider.capabilities_for_model(selection.model)
        wants_stream = bool(body.get("stream"))
        if wants_stream and not caps.streaming:
            raise UnsupportedCapabilityError(
                "Model '{0}' on provider '{1}' does not support streaming.".format(selection.model, selection.provider_id)
            )
        tools = body.get("tools")
        if tools and not caps.tool_calling:
            raise UnsupportedCapabilityError(
                "Model '{0}' on provider '{1}' does not support tool calling.".format(selection.model, selection.provider_id)
            )
        if body.get("parallel_tool_calls") and not caps.parallel_tool_calls:
            raise UnsupportedCapabilityError(
                "Model '{0}' on provider '{1}' does not support parallel tool calls.".format(selection.model, selection.provider_id)
            )
        response_format = body.get("response_format")
        if response_format and not caps.structured_output:
            # Plain text response formats are a no-op and remain compatible.
            fmt_type = response_format.get("type") if isinstance(response_format, dict) else response_format
            if fmt_type not in (None, "text"):
                raise UnsupportedCapabilityError(
                    "Model '{0}' on provider '{1}' does not support structured output.".format(selection.model, selection.provider_id)
                )
        image, video = self._contains_media(body.get("input", body.get("messages", [])))
        if image and not caps.image_input:
            raise UnsupportedCapabilityError(
                "Model '{0}' on provider '{1}' does not support image input.".format(selection.model, selection.provider_id)
            )
        if video and not caps.video_input:
            raise UnsupportedCapabilityError(
                "Model '{0}' on provider '{1}' does not support video input.".format(selection.model, selection.provider_id)
            )

    def _payload_for_selection(self, payload: Dict[str, Any], selection: ProviderSelection) -> Dict[str, Any]:
        result = dict(payload)
        # Router-only fields must never leak to an arbitrary compatible API.
        result.pop("provider", None)
        result.pop("free_codex_fallback", None)
        metadata = result.get("metadata")
        if isinstance(metadata, dict):
            local_keys = ("free_codex_provider", "provider", "free_codex_fallback")
            if not isinstance(selection.provider, PuterWebProvider):
                local_keys = local_keys + ("free_codex_conversation_id",)
            result["metadata"] = {
                key: value for key, value in metadata.items() if key not in local_keys
            }
        if not isinstance(selection.provider, PuterWebProvider):
            result.pop("previous_response_id", None)
        caps = selection.provider.capabilities_for_model(selection.model)
        # Reasoning controls are optional OpenAI extensions. Gracefully omit
        # them for a model that does not actually advertise reasoning instead
        # of fabricating a reasoning field in its response.
        if not caps.reasoning:
            for key in ("reasoning", "reasoning_effort", "thinking"):
                result.pop(key, None)
        if not caps.structured_output:
            response_format = result.get("response_format")
            fmt_type = response_format.get("type") if isinstance(response_format, dict) else response_format
            if fmt_type in (None, "text"):
                result.pop("response_format", None)
        result["model"] = selection.model
        return result

    async def _try_chat(self, selection: ProviderSelection, payload: Dict[str, Any]) -> Dict[str, Any]:
        start = time.monotonic()
        try:
            output = await selection.provider.chat_completion(self._payload_for_selection(payload, selection))
            usage = output.get("usage") if isinstance(output, dict) else None
            if isinstance(usage, dict):
                from ..services.sse_utils import usage_tracker
                asyncio.create_task(usage_tracker.add_usage(usage))
            self.event_logger.event(
                "provider_completed", provider=selection.provider_id, model=selection.model,
                protocol="chat_completions", stream=False, latency_ms=round((time.monotonic() - start) * 1000, 1), status="completed",
                tool_call_count=len((((output.get("choices") or [{}])[0].get("message") or {}).get("tool_calls") or [])),
            )
            return output
        except ProviderError as exc:
            self.event_logger.event(
                "provider_error", provider=selection.provider_id, model=selection.model,
                protocol="chat_completions", stream=False, latency_ms=round((time.monotonic() - start) * 1000, 1),
                status="failed", error_type=exc.error_type,
            )
            raise

    async def chat_completion(self, selection: ProviderSelection, payload: Dict[str, Any]) -> Dict[str, Any]:
        try:
            return await self._try_chat(selection, payload)
        except ProviderUnavailableError:
            for fallback_id in selection.fallback_provider_ids:
                fallback = self.get_provider(fallback_id)
                if not fallback.enabled:
                    continue
                fallback_selection = ProviderSelection(
                    fallback_id, fallback, fallback.resolve_model(selection.model), selection.requested_model,
                    "fallback", [],
                )
                self.validate_capabilities(fallback_selection, payload)
                return await self._try_chat(fallback_selection, payload)
            raise

    async def stream_chat_completion(
        self, selection: ProviderSelection, payload: Dict[str, Any]
    ) -> AsyncGenerator[bytes, None]:
        start = time.monotonic()
        emitted = False
        selected = selection
        try:
            stream = selected.provider.stream_chat_completion(self._payload_for_selection(payload, selected))
            # Parse usage chunks once at the router boundary; provider retry or
            # Responses conversion layers must not charge usage repeatedly.
            from ..services.sse_utils import track_usage_and_forward
            async for chunk in track_usage_and_forward(stream):
                emitted = True
                yield chunk
            self.event_logger.event(
                "provider_completed", provider=selected.provider_id, model=selected.model,
                protocol="chat_completions", stream=True, latency_ms=round((time.monotonic() - start) * 1000, 1), status="completed",
            )
        except ProviderUnavailableError as exc:
            if not emitted and selected.fallback_provider_ids:
                for fallback_id in selected.fallback_provider_ids:
                    fallback = self.get_provider(fallback_id)
                    if not fallback.enabled:
                        continue
                    fallback_selection = ProviderSelection(
                        fallback_id, fallback, fallback.resolve_model(selected.model), selected.requested_model, "fallback", []
                    )
                    self.validate_capabilities(fallback_selection, payload)
                    async for chunk in self.stream_chat_completion(fallback_selection, payload):
                        yield chunk
                    return
            self.event_logger.event(
                "provider_error", provider=selected.provider_id, model=selected.model,
                protocol="chat_completions", stream=True, latency_ms=round((time.monotonic() - start) * 1000, 1),
                status="failed", error_type=exc.error_type,
            )
            raise

    async def completion(self, selection: ProviderSelection, payload: Dict[str, Any]) -> Dict[str, Any]:
        return await selection.provider.completion(self._payload_for_selection(payload, selection))

    async def stream_completion(self, selection: ProviderSelection, payload: Dict[str, Any]) -> AsyncGenerator[bytes, None]:
        async for chunk in selection.provider.stream_completion(self._payload_for_selection(payload, selection)):
            yield chunk

    def remember_response(self, response_id: str, selection: ProviderSelection, *, ttl_seconds: int = 7200) -> None:
        if not response_id:
            return
        self._response_sticky[response_id] = (
            selection.provider_id,
            selection.model,
            time.monotonic() + max(60, ttl_seconds),
        )
        # Give browser provider a stable conversation association when it has
        # one. Tool-call IDs remain the primary continuation mechanism.
        if isinstance(selection.provider, PuterWebProvider):
            selection.provider.remember_response(
                response_id, selection.provider.last_conversation_id
            )
        now = time.monotonic()
        if len(self._response_sticky) > 2048:
            self._response_sticky = {k: v for k, v in self._response_sticky.items() if v[2] > now}

    async def providers_status(self, *, probe: bool = False) -> List[Dict[str, Any]]:
        result: List[Dict[str, Any]] = []
        for provider in self.providers.values():
            health = await provider.health(probe=probe)
            row = provider.describe()
            row["health"] = health.to_dict()
            if isinstance(provider, PuterWebProvider):
                row["browser"] = provider.manager.status()
            result.append(row)
        return result

    async def list_models(self, *, discover: bool = False) -> List[Dict[str, Any]]:
        models: List[Dict[str, Any]] = []
        seen = set()
        for provider_id, provider in self.providers.items():
            if not provider.enabled:
                continue
            items = await provider.list_models() if discover else [provider.model_metadata()]
            for item in items:
                data = item.to_dict()
                # Preserve raw model ID plus a stable local provider-qualified
                # alias so two providers can expose the same model name.
                advertised_ids = [data["id"], "{0}:{1}".format(provider_id, data["id"])]
                advertised_ids.extend(data.get("aliases") or [])
                for model_id in advertised_ids:
                    key = (provider_id, model_id)
                    if key in seen:
                        continue
                    seen.add(key)
                    clone = dict(data)
                    clone["id"] = model_id
                    models.append(clone)
        # Legacy aliases retained for existing Codex configs and clients.
        nvidia = self.providers.get("nvidia")
        if nvidia and nvidia.enabled:
            for legacy in ("nvidia_nim", "gpt-3.5-turbo", "gpt-4o", "gpt-4"):
                if not any(item["id"] == legacy for item in models):
                    data = nvidia.model_metadata().to_dict()
                    data["id"] = legacy
                    data["aliases"] = [nvidia.default_model] if nvidia.default_model else []
                    models.append(data)
        return models
