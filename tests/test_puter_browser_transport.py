import asyncio

import pytest

from free_codex.providers.base import ProviderUnavailableError
from free_codex.services.puter_browser import PuterBrowserManager
from free_codex.utils.config import ProviderDefinition, ProviderType


def _ready_manager():
    definition = ProviderDefinition(
        id="puter_web", type=ProviderType.PUTER_WEB, enabled=True, default_model="m"
    )
    manager = PuterBrowserManager(definition, bridge_base_url="http://127.0.0.1:8080")
    session = manager._new_session()
    session.connected.set()
    session.ready.set()
    session.authenticated = True
    session.sdk_ready = True
    session.state = "ready"
    manager._session = session
    return manager, session


def test_mock_browser_transport_correlates_stream_events_and_cleans_up():
    manager, session = _ready_manager()

    async def run():
        events = []

        async def consume():
            async for event in manager.request_events({"model": "m", "stream": True}, request_id="r1"):
                events.append(event)

        task = asyncio.create_task(consume())
        command = await asyncio.wait_for(session.outgoing.get(), timeout=1)
        assert command["request_id"] == "r1"
        await manager.receive_bridge_message(session, {"type": "event", "request_id": "r1", "event": {"type": "delta", "delta": "a"}})
        await manager.receive_bridge_message(session, {"type": "event", "request_id": "r1", "event": {"type": "completed"}})
        await task
        assert [event["type"] for event in events] == ["delta", "completed"]
        assert manager.status()["active_requests"] == 0

    asyncio.run(run())


def test_mock_browser_transport_timeout_and_disconnect_do_not_hang():
    manager, session = _ready_manager()

    async def timeout_case():
        async def consume():
            async for _ in manager.request_events({"model": "m"}, request_id="timeout", timeout=0.01):
                pass

        task = asyncio.create_task(consume())
        await session.outgoing.get()
        with pytest.raises(ProviderUnavailableError):
            await task

    asyncio.run(timeout_case())

    manager, session = _ready_manager()

    async def disconnect_case():
        async def consume():
            async for _ in manager.request_events({"model": "m"}, request_id="disconnect", timeout=1):
                pass

        task = asyncio.create_task(consume())
        await session.outgoing.get()
        await manager.mark_disconnected("simulated crash")
        with pytest.raises(ProviderUnavailableError):
            await task
        assert manager.status()["connected"] is False

    asyncio.run(disconnect_case())
