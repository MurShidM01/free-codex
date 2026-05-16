from free_codex.services.responses_input_expand import response_items_to_chat_messages


def test_batched_function_calls_then_tool_output():
    items = [
        {"type": "function_call", "call_id": "c1", "name": "run", "arguments": "{}"},
        {"type": "function_call", "call_id": "c2", "name": "read", "arguments": '{"p":"/"}'},
        {
            "type": "function_call_output",
            "call_id": "c1",
            "output": "stdout line",
        },
    ]
    msgs = response_items_to_chat_messages(items)
    assert msgs[0]["role"] == "assistant"
    assert len(msgs[0]["tool_calls"]) == 2
    assert msgs[0]["tool_calls"][0]["id"] == "c1"
    assert msgs[1]["role"] == "tool"
    assert msgs[1]["tool_call_id"] == "c1"


def test_apply_patch_call_output_encoding():
    items = [
        {
            "type": "apply_patch_call_output",
            "call_id": "patch1",
            "status": "completed",
            "output": "done",
        }
    ]
    msgs = response_items_to_chat_messages(items)
    assert msgs[0]["role"] == "tool"
    assert msgs[0]["tool_call_id"] == "patch1"
    assert "completed" in msgs[0]["content"]
