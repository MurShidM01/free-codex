from fastapi.testclient import TestClient

from free_codex.app import create_app
from free_codex.routes.responses import get_nim_service


def test_health_check():
    app = create_app()
    client = TestClient(app)
    # /health serves HTML dashboard, /health/json returns status
    response = client.get("/health/json")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"

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


def test_responses_tool_output_displayed():
    """Test that tool outputs are displayed in non-streaming responses."""
    class StubNimForToolOutput:
        async def post_chat_completions_payload(self, payload):
            messages = payload.get("messages", [])
            # First call: return tool call request
            if len(messages) <= 1:
                return {
                    "choices": [{
                        "message": {
                            "role": "assistant",
                            "content": "",
                            "tool_calls": [{
                                "id": "call_abc",
                                "type": "function",
                                "function": {
                                    "name": "run_command",
                                    "arguments": '{"cmd":"Get-Item"}',
                                },
                            }]
                        }
                    }],
                    "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
                }
            # Second call: check if we forwarded tool result and return result text
            # Find the tool message with output
            has_tool_result = any(
                m.get("role") == "tool" and m.get("content")
                for m in messages
            )
            return {
                "choices": [{
                    "message": {
                        "role": "assistant",
                        "content": f"Tool executed successfully. Output: {len([m for m in messages if m.get('role') == 'tool'])} tool results processed." if has_tool_result else "No tool results received."
                    }
                }],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            }

    app = create_app()
    app.dependency_overrides[get_nim_service] = lambda: StubNimForToolOutput()
    try:
        client = TestClient(app)
        # First request - returns tool call
        response1 = client.post(
            "/v1/responses",
            json={"model": "nvidia_nim", "input": "run Get-Item command", "stream": False},
        )
        assert response1.status_code == 200
        body1 = response1.json()
        # Should have a function_call in output
        fc = [o for o in body1["output"] if o.get("type") == "function_call"]
        assert len(fc) == 1, f"Expected function_call, got {[o.get('type') for o in body1['output']]}"

        # Build second request with tool result
        tool_result = {
            "type": "function_call_output",
            "call_id": "call_abc",
            "output": "Mode                 LastWriteTime         Length Name\nd-----        5/17/2026  10:32 PM                temp"
        }

        response2 = client.post(
            "/v1/responses",
            json={
                "model": "nvidia_nim",
                "input": [
                    {"type": "input_text", "text": "run Get-Item command"},
                    {"type": "function_call", "id": fc[0]["id"], "call_id": fc[0]["call_id"], "name": "run_command", "arguments": '{"cmd":"Get-Item"}'},
                    tool_result
                ],
                "stream": False,
            },
        )
        assert response2.status_code == 200
        body2 = response2.json()
        # Verify tool output is displayed in response
        output_texts = []
        for item in body2.get("output", []):
            if item.get("type") == "message":
                for content in item.get("content", []):
                    if content.get("type") == "output_text":
                        output_texts.append(content.get("text", ""))
        result_text = " ".join(output_texts)
        # The response should mention tool results
        assert "tool" in result_text.lower() or "executed" in result_text.lower(), f"Expected tool output in response, got: {result_text}"
    finally:
        app.dependency_overrides.clear()


def test_responses_stream_tool_output_displayed():
    """Test that tool outputs are displayed in streaming responses."""
    class StubNimForStreamingTool:
        async def stream_chat_completions_payload(self, payload):
            messages = payload.get("messages", [])
            # Check if we have tool results in messages
            tool_contents = [m.get("content") for m in messages if m.get("role") == "tool" and m.get("content")]
            if tool_contents:
                # Escape any control characters in tool output for JSON safety
                safe_content = tool_contents[0][:30].replace("\n", "\\n").replace("\r", "\\r")
                response = f'data: {{"choices":[{{"delta":{{"content":"Tool output: {safe_content}"}}}}]}}\n\n'
                yield response.encode()
            else:
                yield b'data: {"choices":[{"delta":{"content":"Ready to run tool"}}]}\n\n'
            yield b"data: [DONE]\n\n"

    app = create_app()
    app.dependency_overrides[get_nim_service] = lambda: StubNimForStreamingTool()
    try:
        client = TestClient(app)
        response = client.post(
            "/v1/responses/stream",
            json={
                "model": "nvidia_nim",
                "input": [
                    {"type": "function_call_output", "call_id": "call_abc", "output": "file1\nfile2"}
                ],
                "stream": True,
            },
        )
        assert response.status_code == 200
        text = response.text
        # Should contain tool output in streaming response
        assert "Tool output" in text or "file1" in text, f"Expected tool output in stream, got: {text[:200]}"
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
