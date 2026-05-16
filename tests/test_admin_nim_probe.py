import asyncio

import httpx

from free_codex.services.admin_nim_probe import nim_fetch_models, nim_ping_chat


def test_nim_fetch_models_parses_count():
    def handler(request: httpx.Request) -> httpx.Response:
        assert "/models" in str(request.url)
        return httpx.Response(200, json={"data": [{"id": "a"}, {"id": "b"}]})

    transport = httpx.MockTransport(handler)

    async def run():
        async with httpx.AsyncClient(transport=transport) as client:
            return await nim_fetch_models(
                client, base_url="https://api.example/v1/", api_key="k"
            )

    out = asyncio.run(run())
    assert out["ok"] is True
    assert out["model_count"] == 2


def test_nim_ping_chat_ok():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/chat/completions")
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"role": "assistant", "content": "pong"}}],
            },
        )

    transport = httpx.MockTransport(handler)

    async def run():
        async with httpx.AsyncClient(transport=transport) as client:
            return await nim_ping_chat(
                client,
                base_url="https://api.example/v1",
                api_key="k",
                model="m",
            )

    out = asyncio.run(run())
    assert out["ok"] is True
    assert "pong" in (out.get("assistant_preview") or "")
