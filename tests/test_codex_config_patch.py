from free_codex.utils.codex_config_patch import apply_fc_init_codex_proxy_overrides


def test_overrides_model_provider_and_base_url():
    src = '''
model = "other"
model_provider = "other_provider"
[model_providers.free_codex_nim]
base_url = "http://old:9/v1"
'''.strip()
    out = apply_fc_init_codex_proxy_overrides(src)
    assert 'model = "minimaxai/minimax-m2.7"' in out
    assert 'model_provider = "free_codex_nim"' in out
    assert 'base_url = "http://127.0.0.1:8080/v1"' in out
    # Provider block must declare the Responses wire API.
    assert 'wire_api = "responses"' in out


def test_inserts_model_provider_if_missing():
    src = 'model = "x"\n'
    out = apply_fc_init_codex_proxy_overrides(src)
    assert 'model = "minimaxai/minimax-m2.7"' in out
    assert 'model_provider = "free_codex_nim"' in out
    assert out.index("model =") < out.index("model_provider")


def test_injects_wire_api_when_missing_from_provider_block():
    """Existing configs without wire_api must get one injected under the
    [model_providers.free_codex_nim] table."""
    src = '''
model = "other"
model_provider = "free_codex_nim"
[model_providers.free_codex_nim]
name = "Free Codex (local NIM proxy)"
base_url = "http://127.0.0.1:8080/v1"
'''.strip()
    out = apply_fc_init_codex_proxy_overrides(src)
    assert 'wire_api = "responses"' in out
    # The wire_api line must appear inside the provider table, not before it.
    assert out.index("[model_providers.free_codex_nim]") < out.index('wire_api =')


def test_overrides_legacy_chat_wire_api_to_responses():
    """A stale `wire_api = "chat"` must be rewritten to "responses" since
    Codex no longer accepts the chat value."""
    src = '''
model = "x"
model_provider = "free_codex_nim"
[model_providers.free_codex_nim]
base_url = "http://127.0.0.1:8080/v1"
wire_api = "chat"
'''.strip()
    out = apply_fc_init_codex_proxy_overrides(src)
    assert 'wire_api = "chat"' not in out
    assert 'wire_api = "responses"' in out
