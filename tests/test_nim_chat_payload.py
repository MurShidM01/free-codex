from free_codex.services.nim_chat_payload import (
    normalize_chat_payload_for_nim,
    normalize_one_tool,
)


def test_flat_tool_gets_function_wrapped():
    raw = {
        "type": "function",
        "name": "bash",
        "description": "run shell",
        "parameters": {"type": "object", "properties": {}},
    }
    out = normalize_one_tool(raw)
    assert out is not None
    assert "function" in out
    assert out["function"]["name"] == "bash"
    assert out["function"]["description"] == "run shell"


def test_normalize_payload_tool_choice_when_no_tools():
    payload = {"messages": [{"role": "user", "content": "hi"}], "tool_choice": {"type": "function", "name": "x"}}
    normalize_chat_payload_for_nim(payload)
    assert "tools" not in payload or not payload.get("tools")
    assert payload["tool_choice"] == "none"
