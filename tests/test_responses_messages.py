from free_codex.services.responses_messages import responses_body_to_chat_messages


def test_string_input():
    msgs, model = responses_body_to_chat_messages(
        {"model": "nvidia_nim", "input": "hello"}
    )
    assert model == "nvidia_nim"
    assert msgs == [{"role": "user", "content": "hello"}]


def test_instructions_and_array_input():
    body = {
        "model": "x",
        "instructions": "sys",
        "input": [
            {
                "role": "user",
                "content": [{"type": "input_text", "text": "line"}],
            }
        ],
    }
    msgs, model = responses_body_to_chat_messages(body)
    assert model == "x"
    assert msgs[0] == {"role": "system", "content": "sys"}
    assert msgs[1] == {"role": "user", "content": "line"}
