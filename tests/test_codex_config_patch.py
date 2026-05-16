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


def test_inserts_model_provider_if_missing():
    src = 'model = "x"\n'
    out = apply_fc_init_codex_proxy_overrides(src)
    assert 'model = "minimaxai/minimax-m2.7"' in out
    assert 'model_provider = "free_codex_nim"' in out
    assert out.index("model =") < out.index("model_provider")
