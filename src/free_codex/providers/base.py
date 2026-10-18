"""Provider-neutral contracts used by the Free Codex router.

The public API exposed by Free Codex is always OpenAI-compatible.  Providers
are deliberately internal transports: a provider never changes the URL or the
wire protocol used by Codex.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator, Dict, List, Optional


class ProviderError(Exception):
    """A sanitized error that can safely cross the local proxy boundary."""

    status_code = 502
    error_type = "provider_error"
    retryable = False

    def __init__(
        self,
        message: str,
        *,
        status_code: Optional[int] = None,
        error_type: Optional[str] = None,
        retryable: Optional[bool] = None,
    ) -> None:
        super().__init__(message)
        if status_code is not None:
            self.status_code = status_code
        if error_type is not None:
            self.error_type = error_type
        if retryable is not None:
            self.retryable = retryable

    def as_openai_error(self) -> Dict[str, Any]:
        return {
            "error": {
                "message": str(self),
                "type": self.error_type,
            }
        }


class ProviderNotFoundError(ProviderError):
    status_code = 404
    error_type = "provider_not_found"


class ProviderUnavailableError(ProviderError):
    status_code = 503
    error_type = "provider_unavailable"
    retryable = True


class ProviderAuthenticationRequiredError(ProviderError):
    status_code = 503
    error_type = "authentication_required"


class UnsupportedCapabilityError(ProviderError):
    status_code = 400
    error_type = "unsupported_capability"


class ProviderProtocolError(ProviderError):
    status_code = 502
    error_type = "provider_protocol_error"


@dataclass
class ProviderCapabilities:
    """Capabilities actually implemented by a provider/model route.

    Values are intentionally conservative.  A provider configuration can add
    model-specific capabilities, but a route must not claim a feature simply
    because some other model from the same vendor supports it.
    """

    text_input: bool = True
    image_input: bool = False
    video_input: bool = False
    streaming: bool = True
    tool_calling: bool = True
    parallel_tool_calls: bool = True
    structured_output: bool = False
    reasoning: bool = False
    embeddings: bool = False
    context_window: Optional[int] = None
    max_output_tokens: Optional[int] = None
    provider_notes: str = ""

    @classmethod
    def from_mapping(
        cls, value: Optional[Dict[str, Any]], base: Optional["ProviderCapabilities"] = None
    ) -> "ProviderCapabilities":
        """Merge a trusted configuration mapping into a capability object."""
        data = (base or cls()).to_dict()
        if isinstance(value, dict):
            for key in data:
                if key in value and value[key] is not None:
                    data[key] = value[key]
        return cls(**data)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "text_input": self.text_input,
            "image_input": self.image_input,
            "video_input": self.video_input,
            "streaming": self.streaming,
            "tool_calling": self.tool_calling,
            "parallel_tool_calls": self.parallel_tool_calls,
            "structured_output": self.structured_output,
            "reasoning": self.reasoning,
            "embeddings": self.embeddings,
            "context_window": self.context_window,
            "max_output_tokens": self.max_output_tokens,
            "provider_notes": self.provider_notes,
        }


@dataclass
class ProviderModel:
    id: str
    provider: str
    capabilities: ProviderCapabilities
    aliases: List[str] = field(default_factory=list)
    owned_by: str = "free-codex"
    ready: Optional[bool] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "object": "model",
            "owned_by": self.owned_by,
            "provider": self.provider,
            "aliases": list(self.aliases),
            "capabilities": self.capabilities.to_dict(),
            "ready": self.ready,
        }


@dataclass
class ProviderHealth:
    provider: str
    configured: bool
    ready: bool
    status: str
    message: str = ""
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "provider": self.provider,
            "configured": self.configured,
            "ready": self.ready,
            "status": self.status,
            "message": self.message,
            "details": self.details,
        }


class Provider(abc.ABC):
    """Common internal transport contract.

    Implementations receive and return OpenAI Chat/Completions shaped data.
    The shared Responses bridge performs Responses <-> Chat conversion once,
    rather than duplicating that conversion in every provider.
    """

    provider_type = "custom_openai"

    def __init__(
        self,
        provider_id: str,
        *,
        default_model: str = "",
        enabled: bool = True,
        capabilities: Optional[ProviderCapabilities] = None,
    ) -> None:
        self.id = provider_id
        self.default_model = default_model
        self.enabled = enabled
        self.capabilities = capabilities or ProviderCapabilities()

    def resolve_model(self, requested_model: str) -> str:
        return (requested_model or self.default_model or "").strip()

    def capabilities_for_model(self, model: str) -> ProviderCapabilities:
        return self.capabilities

    def model_metadata(self, model: Optional[str] = None) -> ProviderModel:
        selected = self.resolve_model(model or self.default_model)
        return ProviderModel(
            id=selected or self.id,
            provider=self.id,
            capabilities=self.capabilities_for_model(selected),
            owned_by=self.provider_type,
        )

    async def start(self) -> None:
        """Start optional transport resources.  Kept lazy by default."""

    async def stop(self) -> None:
        """Stop optional transport resources and cancel pending work."""

    async def list_models(self) -> List[ProviderModel]:
        return [self.model_metadata()]

    async def health(self, *, probe: bool = False) -> ProviderHealth:
        if not self.enabled:
            return ProviderHealth(self.id, configured=False, ready=False, status="disabled")
        return ProviderHealth(self.id, configured=True, ready=True, status="ready")

    async def handle_responses(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Handle a shared Responses->Chat-normalized provider payload.

        The FastAPI route owns client-facing Responses object/SSE conversion;
        this hook keeps providers capable of direct dispatch in internal tests
        or future native Responses transports without duplicating converters.
        """
        return await self.chat_completion(payload)

    async def stream_responses(self, payload: Dict[str, Any]) -> AsyncGenerator[bytes, None]:
        async for chunk in self.stream_chat_completion(payload):
            yield chunk

    async def handle_chat_completions(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return await self.chat_completion(payload)

    @abc.abstractmethod
    async def chat_completion(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Perform a non-streaming OpenAI Chat Completions request."""

    @abc.abstractmethod
    async def stream_chat_completion(self, payload: Dict[str, Any]) -> AsyncGenerator[bytes, None]:
        """Yield OpenAI-style SSE bytes for a Chat Completions request."""
        # The body makes this an async generator for static type checkers.
        if False:  # pragma: no cover
            yield b""

    async def completion(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        raise UnsupportedCapabilityError(
            "The selected provider does not implement legacy text completions. "
            "Use /v1/chat/completions or /v1/responses."
        )

    async def stream_completion(self, payload: Dict[str, Any]) -> AsyncGenerator[bytes, None]:
        raise UnsupportedCapabilityError(
            "The selected provider does not implement streaming legacy text completions."
        )
        if False:  # pragma: no cover
            yield b""

    async def cancel(self, request_id: str) -> None:
        """Best-effort cancellation.  Providers without a cancel API may ignore it."""

    def describe(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "type": self.provider_type,
            "enabled": self.enabled,
            "default_model": self.default_model,
            "capabilities": self.capabilities.to_dict(),
        }
