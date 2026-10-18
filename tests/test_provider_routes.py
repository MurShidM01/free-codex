from fastapi.testclient import TestClient

from free_codex.app import create_app
from free_codex.routes.chat import get_provider_router


class StubRouter:
    def __init__(self):
        self.selected = None
        self.payload = None

    def select(self, *, body, requested_model, headers=None):
        self.selected = (body, requested_model)
        return type("Selection", (), {"model": "upstream-model", "provider_id": "stub"})()

    async def chat_completion(self, selection, payload):
        self.payload = payload
        return {
            "id": "chatcmpl_stub",
            "object": "chat.completion",
            "model": payload["model"],
            "choices": [{"message": {"role": "assistant", "content": "routed"}, "finish_reason": "stop"}],
        }

    async def stream_chat_completion(self, selection, payload):
        yield b'data: {"choices":[{"delta":{"content":"routed"}}]}\n\n'
        yield b"data: [DONE]\n\n"

    def remember_response(self, *args, **kwargs):
        return None


def test_chat_route_dispatches_through_provider_router_without_changing_client_url():
    app = create_app()
    stub = StubRouter()
    app.dependency_overrides[get_provider_router] = lambda: stub
    try:
        client = TestClient(app)
        response = client.post(
            "/v1/chat/completions",
            json={"model": "puter_web:vendor/model", "messages": [{"role": "user", "content": "hello"}]},
        )
        assert response.status_code == 200
        assert response.json()["choices"][0]["message"]["content"] == "routed"
        # The route preserves the client model for selection; ProviderRouter
        # replaces it with its resolved upstream model during dispatch.
        assert stub.payload["model"] == "puter_web:vendor/model"
    finally:
        app.dependency_overrides.clear()
