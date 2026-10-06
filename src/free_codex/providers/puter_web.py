"""Browser-mediated Puter Web provider using only the official Puter.js SDK."""

from __future__ import annotations

import json
import time
import uuid
from typing import Any, AsyncGenerator, Dict, List, Optional

from ..services.provider_logging import ProviderEventLogger
from ..services.puter_browser import PuterBrowserManager
from ..utils.config import ProviderDefinition
from .base import (
    Provider,
    ProviderCapabilities,
    ProviderHealth,
    ProviderModel,
    ProviderProtocolError,
)


class PuterWebProvider(Provider):
    """Adapt hidden-browser Puter.js events to OpenAI Chat Completions data.

    The provider intentionally never executes a requested tool.  It returns
    function calls to Codex, remembers their browser conversation, and only
    forwards a later ``function_call_output`` / ``role=tool`` result supplied
    by the client back to Puter.js.
    """

    provider_type = "puter_web"

    def __init__(
        self,
        definition: ProviderDefinition,
        *,
        manager: Optional[PuterBrowserManager] = None,
        event_logger: Optional[ProviderEventLogger] = None,
    ) -> None:
        caps = ProviderCapabilities.from_mapping(definition.capabilities)
        super().__init__(
            definition.id,
            default_model=definition.default_model,
            enabled=definition.enabled,
            capabilities=caps,
        )
        self.definition = definition
        self.manager = manager or PuterBrowserManager(definition, event_logger=event_logger)
        self.event_logger = event_logger or ProviderEventLogger()
        self._call_conversations: Dict[str, str] = {}
        self._response_conversations: Dict[str, str] = {}
        self._last_conversation_id = ""

    def resolve_model(self, requested_model: str) -> str:
        return self.definition.resolve_model(requested_model)

    def capabilities_for_model(self, model: str) -> ProviderCapabilities:
        return ProviderCapabilities.from_mapping(
            self.definition.capabilities_for_model(model), self.capabilities
        )

    async def start(self) -> None:
        # Start only when this provider is selected/on-demand.  It remains
        # headless for normal server operation.
        await self.manager.start(wait_for_connection=True)

    async def stop(self) -> None:
        await self.manager.stop()

    def _conversation_for_payload(self, payload: Dict[str, Any]) -> str:
        metadata = payload.get("metadata")
        if isinstance(metadata, dict):
            explicit = metadata.get("free_codex_conversation_id")
            if isinstance(explicit, str) and explicit:
                return explicit
        previous = payload.get("previous_response_id")
        if isinstance(previous, str) and previous in self._response_conversations:
            return self._response_conversations[previous]
        for result in self._extract_tool_results(payload):
            known = self._call_conversations.get(result["call_id"])
            if known:
                return known
        return "puter_conv_{0}".format(uuid.uuid4().hex)

    @staticmethod
    def _extract_tool_results(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []
        for message in payload.get("messages") or []:
            if not isinstance(message, dict) or message.get("role") != "tool":
                continue
            call_id = message.get("tool_call_id") or message.get("call_id")
            if not call_id:
                continue
            content = message.get("content", "")
            if not isinstance(content, str):
                try:
                    content = json.dumps(content)
                except (TypeError, ValueError):
                    content = str(content)
            results.append({"call_id": str(call_id), "output": content})
        return results

    @staticmethod
    def _normalise_messages(messages: Any) -> List[Dict[str, Any]]:
        """Keep OpenAI content blocks intact for documented SDK media support."""
        if not isinstance(messages, list):
            return []
        normalized: List[Dict[str, Any]] = []
        for raw in messages:
            if not isinstance(raw, dict):
                continue
            role = str(raw.get("role") or "user")
            message: Dict[str, Any] = {"role": role, "content": raw.get("content", "")}
            for key in ("name", "tool_call_id", "tool_calls"):
                if key in raw and raw[key] is not None:
                    message[key] = raw[key]
            normalized.append(message)
        return normalized

    def _bridge_payload(self, payload: Dict[str, Any], conversation_id: str) -> Dict[str, Any]:
        model = self.resolve_model(str(payload.get("model") or ""))
        if not model:
            raise ProviderProtocolError(
                "No Puter Web model is configured. Set PUTER_WEB_MODEL or select a configured model alias."
            )
        known_conversations = set(self._call_conversations.values()) | set(self._response_conversations.values())
        request: Dict[str, Any] = {
            "model": model,
            "messages": self._normalise_messages(payload.get("messages")),
            "stream": bool(payload.get("stream", False)),
            "conversation_id": conversation_id,
            "append_messages": conversation_id in known_conversations,
            "tool_results": self._extract_tool_results(payload),
        }
        for key in (
            "temperature", "top_p", "max_tokens", "max_output_tokens", "tools",
            "tool_choice", "parallel_tool_calls", "response_format", "reasoning_effort",
        ):
            if key in payload and payload[key] is not None:
                request[key] = payload[key]
        return request

    @staticmethod
    def _chat_id() -> str:
        return "chatcmpl_puter_{0}".format(uuid.uuid4().hex[:24])

    def _register_tool_calls(self, tool_calls: List[Dict[str, Any]], conversation_id: str) -> None:
        for call in tool_calls:
            call_id = str(call.get("id") or "")
            if call_id:
                self._call_conversations[call_id] = conversation_id

    async def _collect(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        conversation_id = self._conversation_for_payload(payload)
        bridge_payload = self._bridge_payload(payload, conversation_id)
        text_parts: List[str] = []
        calls: List[Dict[str, Any]] = []
        usage: Optional[Dict[str, Any]] = None
        async for event in self.manager.request_events(
            bridge_payload,
            conversation_id=conversation_id,
        ):
            kind = str(event.get("type") or "")
            if kind == "delta":
                value = event.get("delta", "")
                if isinstance(value, str):
                    text_parts.append(value)
            elif kind == "tool_call" and isinstance(event.get("tool_call"), dict):
                call = event["tool_call"]
                if not any(existing.get("id") == call.get("id") for existing in calls):
                    calls.append(call)
            elif kind == "completed":
                for call in event.get("tool_calls") or []:
                    if isinstance(call, dict) and not any(existing.get("id") == call.get("id") for existing in calls):
                        calls.append(call)
                if isinstance(event.get("usage"), dict):
                    usage = event["usage"]
                if isinstance(event.get("conversation_id"), str):
                    conversation_id = event["conversation_id"]
        self._register_tool_calls(calls, conversation_id)
        self._last_conversation_id = conversation_id
        message: Dict[str, Any] = {"role": "assistant", "content": "".join(text_parts)}
        if calls:
            message["tool_calls"] = calls
        return {
            "id": self._chat_id(),
            "object": "chat.completion",
            "created": int(time.time()),
            "model": bridge_payload["model"],
            "choices": [{
                "index": 0,
                "message": message,
                "finish_reason": "tool_calls" if calls else "stop",
            }],
            "usage": usage,
            "_free_codex_conversation_id": conversation_id,
        }

    async def chat_completion(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        result = await self._collect(payload)
        # This internal field is used by the Responses route only when it binds
        # a response ID. It must not leak to chat-completions clients.
        result.pop("_free_codex_conversation_id", None)
        return result

    async def stream_chat_completion(self, payload: Dict[str, Any]) -> AsyncGenerator[bytes, None]:
        conversation_id = self._conversation_for_payload(payload)
        bridge_payload = self._bridge_payload(payload, conversation_id)
        chat_id = self._chat_id()
        created = int(time.time())
        model = bridge_payload["model"]
        tool_calls: List[Dict[str, Any]] = []
        started = False
        try:
            async for event in self.manager.request_events(
                bridge_payload,
                conversation_id=conversation_id,
            ):
                kind = str(event.get("type") or "")
                if kind == "delta":
                    delta = event.get("delta", "")
                    if not isinstance(delta, str) or not delta:
                        continue
                    role = "assistant" if not started else None
                    started = True
                    chunk = {
                        "id": chat_id,
                        "object": "chat.completion.chunk",
                        "created": created,
                        "model": model,
                        "choices": [{"index": 0, "delta": {"role": role, "content": delta}, "finish_reason": None}],
                    }
                    # Omit role=None so strict clients do not see it.
                    if role is None:
                        chunk["choices"][0]["delta"].pop("role")
                    yield "data: {0}\n\n".format(json.dumps(chunk, separators=(",", ":"))).encode("utf-8")
                elif kind == "tool_call" and isinstance(event.get("tool_call"), dict):
                    call = event["tool_call"]
                    if not any(existing.get("id") == call.get("id") for existing in tool_calls):
                        tool_calls.append(call)
                        function = call.get("function") if isinstance(call.get("function"), dict) else {}
                        initial = {
                            "index": len(tool_calls) - 1,
                            "id": call.get("id"),
                            "type": "function",
                            "function": {"name": function.get("name", ""), "arguments": function.get("arguments", "")},
                        }
                        chunk = {
                            "id": chat_id,
                            "object": "chat.completion.chunk",
                            "created": created,
                            "model": model,
                            "choices": [{"index": 0, "delta": {"tool_calls": [initial]}, "finish_reason": None}],
                        }
                        yield "data: {0}\n\n".format(json.dumps(chunk, separators=(",", ":"))).encode("utf-8")
                elif kind == "completed":
                    for call in event.get("tool_calls") or []:
                        if isinstance(call, dict) and not any(existing.get("id") == call.get("id") for existing in tool_calls):
                            tool_calls.append(call)
                    next_conversation = event.get("conversation_id")
                    if isinstance(next_conversation, str) and next_conversation:
                        conversation_id = next_conversation
            self._register_tool_calls(tool_calls, conversation_id)
            self._last_conversation_id = conversation_id
            finish = "tool_calls" if tool_calls else "stop"
            final = {
                "id": chat_id,
                "object": "chat.completion.chunk",
                "created": created,
                "model": model,
                "choices": [{"index": 0, "delta": {}, "finish_reason": finish}],
            }
            yield "data: {0}\n\n".format(json.dumps(final, separators=(",", ":"))).encode("utf-8")
            yield b"data: [DONE]\n\n"
        finally:
            # request_events invokes manager cancellation on generator teardown.
            pass

    async def completion(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        prompt = payload.get("prompt", "")
        if isinstance(prompt, list):
            prompt = "\n".join(str(item) for item in prompt)
        chat = await self.chat_completion({
            "model": payload.get("model"),
            "messages": [{"role": "user", "content": str(prompt)}],
            "temperature": payload.get("temperature"),
            "top_p": payload.get("top_p"),
            "max_tokens": payload.get("max_tokens"),
        })
        text = ((chat.get("choices") or [{}])[0].get("message") or {}).get("content", "")
        return {
            "id": "cmpl_puter_{0}".format(uuid.uuid4().hex[:24]),
            "object": "text_completion",
            "created": int(time.time()),
            "model": chat.get("model"),
            "choices": [{"index": 0, "text": text, "finish_reason": "stop"}],
            "usage": chat.get("usage"),
        }

    async def stream_completion(self, payload: Dict[str, Any]) -> AsyncGenerator[bytes, None]:
        prompt = payload.get("prompt", "")
        if isinstance(prompt, list):
            prompt = "\n".join(str(item) for item in prompt)
        chat_payload = {
            "model": payload.get("model"),
            "messages": [{"role": "user", "content": str(prompt)}],
            "stream": True,
            "temperature": payload.get("temperature"),
            "top_p": payload.get("top_p"),
            "max_tokens": payload.get("max_tokens"),
        }
        async for raw in self.stream_chat_completion(chat_payload):
            if raw == b"data: [DONE]\n\n":
                yield raw
                return
            # Convert only basic content chunks to legacy completion chunks.
            try:
                data = json.loads(raw.decode("utf-8").removeprefix("data: ").strip())
                choice = (data.get("choices") or [{}])[0]
                text = (choice.get("delta") or {}).get("content")
                if text is None:
                    continue
                converted = {
                    "id": data.get("id", ""), "object": "text_completion",
                    "created": data.get("created"), "model": data.get("model"),
                    "choices": [{"index": 0, "text": text, "finish_reason": choice.get("finish_reason")}],
                }
                yield "data: {0}\n\n".format(json.dumps(converted, separators=(",", ":"))).encode("utf-8")
            except (ValueError, TypeError, AttributeError):
                continue

    async def cancel(self, request_id: str) -> None:
        await self.manager.cancel(request_id)

    def model_metadata(self, model: Optional[str] = None) -> ProviderModel:
        metadata = super().model_metadata(model)
        metadata.aliases = [
            alias for alias, value in self.definition.model_aliases.items() if value == metadata.id
        ]
        metadata.ready = bool(self.manager.status().get("authenticated"))
        return metadata

    async def list_models(self) -> List[ProviderModel]:
        model_ids = []
        if self.default_model:
            model_ids.append(self.default_model)
        model_ids.extend(value for value in self.definition.model_aliases.values() if value)
        if not model_ids:
            model_ids = [self.id]
        unique = []
        for model in model_ids:
            if model not in unique:
                unique.append(model)
        return [
            ProviderModel(
                id=model,
                provider=self.id,
                capabilities=self.capabilities_for_model(model),
                aliases=[alias for alias, target in self.definition.model_aliases.items() if target == model],
                owned_by="puter_web",
                ready=bool(self.manager.status().get("authenticated")),
            )
            for model in unique
        ]

    async def health(self, *, probe: bool = False) -> ProviderHealth:
        if not self.enabled:
            return ProviderHealth(self.id, configured=False, ready=False, status="disabled")
        if probe:
            try:
                await self.manager.ensure_ready(require_auth=False)
            except Exception:
                pass
        status = self.manager.status()
        ready = bool(status.get("connected") and status.get("sdk_ready") and status.get("authenticated"))
        if not status.get("connected"):
            state = "not_initialized" if status.get("state") == "not_started" else "browser_unavailable"
        elif not status.get("authenticated"):
            state = "authentication_required"
        elif ready:
            state = "ready"
        else:
            state = str(status.get("state") or "unavailable")
        return ProviderHealth(
            self.id,
            configured=True,
            ready=ready,
            status=state,
            message=(status.get("last_error") or ""),
            details={
                "browser_connected": bool(status.get("connected")),
                "authenticated": bool(status.get("authenticated")),
                "active_requests": int(status.get("active_requests") or 0),
                "active_background_sessions": int(status.get("active_background_sessions") or 0),
                "headless": bool(status.get("headless")),
            },
        )

    @property
    def last_conversation_id(self) -> str:
        return self._last_conversation_id

    def remember_response(self, response_id: str, conversation_id: str) -> None:
        if response_id and conversation_id:
            self._response_conversations[response_id] = conversation_id
