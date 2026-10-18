import asyncio

import pytest

from free_codex.providers.base import ProviderProtocolError
from free_codex.providers.puter_web import PuterWebProvider
from free_codex.services.puter_browser import PuterBrowserManager
from free_codex.utils.config import ProviderDefinition, ProviderType


class FakePuterManager:
    def __init__(self):
        self.requests = []

    async def request_events(self, payload, **kwargs):
        self.requests.append((payload, kwargs))
        if payload.get("tool_results"):
            yield {"type": "delta", "delta": "continued"}
            yield {"type": "completed", "conversation_id": kwargs["conversation_id"]}
            return
        yield {"type": "delta", "delta": "need tool"}
        yield {
            "type": "tool_call",
            "tool_call": {
                "id": "call_stable",
                "type": "function",
                "function": {"name": "read_file", "arguments": '{"path":"a.py"}'},
            },
        }
        yield {"type": "completed", "conversation_id": "conversation-1"}

    async def start(self, **kwargs):
        return None

    async def stop(self):
        return None

    async def cancel(self, request_id):
        return None

    def status(self):
        return {
            "authenticated": True,
            "connected": True,
            "sdk_ready": True,
            "active_requests": 0,
            "state": "ready",
            "headless": True,
            "last_error": "",
        }


def _definition():
    return ProviderDefinition(
        id="puter_web",
        type=ProviderType.PUTER_WEB,
        enabled=True,
        default_model="deepseek/model",
    )


def test_puter_provider_streams_tool_call_and_round_trips_tool_result():
    manager = FakePuterManager()
    provider = PuterWebProvider(_definition(), manager=manager)

    async def run():
        first = await provider.chat_completion({
            "model": "deepseek/model",
            "messages": [{"role": "user", "content": "inspect a.py"}],
            "tools": [{"type": "function", "function": {"name": "read_file", "parameters": {"type": "object"}}}],
        })
        call = first["choices"][0]["message"]["tool_calls"][0]
        assert call["id"] == "call_stable"
        assert call["function"]["name"] == "read_file"

        second = await provider.chat_completion({
            "model": "deepseek/model",
            "messages": [{"role": "tool", "tool_call_id": "call_stable", "content": "contents"}],
        })
        assert second["choices"][0]["message"]["content"] == "continued"

    asyncio.run(run())
    first_payload, first_kwargs = manager.requests[0]
    second_payload, second_kwargs = manager.requests[1]
    assert first_payload["tools"][0]["type"] == "function"
    assert second_payload["tool_results"] == [{"call_id": "call_stable", "output": "contents"}]
    # The model/tool result stays on the original browser conversation.
    assert second_kwargs["conversation_id"] == "conversation-1"


def test_puter_provider_emits_openai_chat_sse_without_real_browser():
    provider = PuterWebProvider(_definition(), manager=FakePuterManager())

    async def collect():
        chunks = []
        async for chunk in provider.stream_chat_completion({
            "model": "deepseek/model",
            "messages": [{"role": "user", "content": "do a tool"}],
            "stream": True,
        }):
            chunks.append(chunk.decode())
        return "".join(chunks)

    text = asyncio.run(collect())
    assert "tool_calls" in text
    assert "call_stable" in text
    assert "[DONE]" in text


class FakeSocket:
    async def send_json(self, value):
        return None


def test_browser_bridge_nonce_origin_and_one_consumer_guard():
    manager = PuterBrowserManager(_definition(), bridge_base_url="http://127.0.0.1:8080")
    session = manager._new_session()
    manager._session = session

    async def run():
        assert manager.validate_page_session(session.session_id, session.nonce)
        with pytest.raises(ProviderProtocolError):
            await manager.attach_websocket(
                FakeSocket(), session_id=session.session_id, nonce=session.nonce,
                origin="https://evil.example", host="evil.example",
            )
        sock = FakeSocket()
        attached = await manager.attach_websocket(
            sock, session_id=session.session_id, nonce=session.nonce,
            origin="http://127.0.0.1:8080", host="127.0.0.1:8080",
        )
        assert attached.connected.is_set()
        with pytest.raises(ProviderProtocolError):
            await manager.attach_websocket(
                FakeSocket(), session_id=session.session_id, nonce=session.nonce,
                origin="http://127.0.0.1:8080", host="127.0.0.1:8080",
            )
        await manager.detach_websocket(session, sock)

    asyncio.run(run())
