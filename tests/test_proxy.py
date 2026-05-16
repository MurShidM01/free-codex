from fastapi.testclient import TestClient

from free_codex.app import create_app
from free_codex.routes.responses import get_nim_service


def test_health_check():
    app = create_app()
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}

def test_list_models():
    app = create_app()
    client = TestClient(app)
    response = client.get("/v1/models")
    assert response.status_code == 200
    data = response.json()
    assert "data" in data
    model_ids = [m["id"] for m in data["data"]]
    assert "test-model" in model_ids
    assert "nvidia_nim" in model_ids
    assert "gpt-4" in model_ids
    assert model_ids[0] == "test-model"


class _StubNimForResponses:
    async def post_chat_completions_payload(self, payload):
        assert payload.get("stream") is False
        assert payload.get("messages")
        return {
            "choices": [{"message": {"role": "assistant", "content": "hello"}}],
            "usage": {
                "prompt_tokens": 1,
                "completion_tokens": 1,
                "total_tokens": 2,
            },
        }

    async def stream_chat_completions_payload(self, payload):
        chunk = b'data: {"choices":[{"delta":{"content":"Hi"}}]}\n\n'
        yield chunk
        yield b"data: [DONE]\n\n"


def test_responses_non_stream_uses_stub():
    app = create_app()
    app.dependency_overrides[get_nim_service] = lambda: _StubNimForResponses()
    try:
        client = TestClient(app)
        response = client.post(
            "/v1/responses",
            json={"model": "nvidia_nim", "input": "ping", "stream": False},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["object"] == "response"
        assert body["status"] == "completed"
        assert body["output"][0]["content"][0]["text"] == "hello"
    finally:
        app.dependency_overrides.clear()


class _StubNimToolCalls:
    async def post_chat_completions_payload(self, payload):
        assert payload.get("stream") is False
        return {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "",
                        "tool_calls": [
                            {
                                "id": "call_abc",
                                "type": "function",
                                "function": {
                                    "name": "write_file",
                                    "arguments": '{"path":"x.py"}',
                                },
                            }
                        ],
                    }
                }
            ],
            "usage": {
                "prompt_tokens": 1,
                "completion_tokens": 1,
                "total_tokens": 2,
            },
        }


def test_responses_non_stream_maps_tool_calls():
    app = create_app()
    app.dependency_overrides[get_nim_service] = lambda: _StubNimToolCalls()
    try:
        client = TestClient(app)
        response = client.post(
            "/v1/responses",
            json={"model": "nvidia_nim", "input": "run tool", "stream": False},
        )
        assert response.status_code == 200
        body = response.json()
        fc = [o for o in body["output"] if o["type"] == "function_call"]
        assert len(fc) == 1
        assert fc[0]["name"] == "write_file"
        assert fc[0]["call_id"] == "call_abc"
    finally:
        app.dependency_overrides.clear()


def test_responses_stream_maps_tool_calls_in_completed():
    app = create_app()
    app.dependency_overrides[get_nim_service] = lambda: _StubNimToolCalls()
    try:
        client = TestClient(app)
        response = client.post(
            "/v1/responses",
            json={"model": "nvidia_nim", "input": "run tool", "stream": True},
        )
        assert response.status_code == 200
        text = response.text
        assert "function_call" in text
        assert "write_file" in text
    finally:
        app.dependency_overrides.clear()


def test_responses_stream_sse_stub():
    app = create_app()
    app.dependency_overrides[get_nim_service] = lambda: _StubNimForResponses()
    try:
        client = TestClient(app)
        response = client.post(
            "/v1/responses",
            json={"model": "nvidia_nim", "input": "ping", "stream": True},
        )
        assert response.status_code == 200
        text = response.text
        assert "event: response.output_text.delta" in text or "output_text.delta" in text
        assert '"sequence_number":0' in text.replace(" ", "")
        assert "event: response.completed" in text or "response.completed" in text
    finally:
        app.dependency_overrides.clear()
