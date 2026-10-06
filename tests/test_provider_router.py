import asyncio

import httpx
import pytest

from free_codex.providers.base import ProviderNotFoundError, UnsupportedCapabilityError
from free_codex.providers.router import ProviderRouter
from free_codex.utils.config import Settings


def _settings(monkeypatch, tmp_path, content):
    path = tmp_path / "providers.toml"
    path.write_text(content, encoding="utf-8")
    monkeypatch.setenv("FREE_CODEX_PROVIDERS_CONFIG", str(path))
    return Settings()


def test_multi_provider_toml_alias_and_capability_override(monkeypatch, tmp_path):
    settings = _settings(
        monkeypatch,
        tmp_path,
        """
[routing]
default_provider = "puter_web"
aliases = { "fast" = "puter_web::deepseek/model" }

[providers.puter_web]
type = "puter_web"
enabled = true
default_model = "deepseek/model"

[providers.puter_web.model_capabilities."deepseek/model"]
image_input = true
streaming = true
tool_calling = true
""",
    )
    definition = settings.provider_definitions["puter_web"]
    assert definition.enabled is True
    assert definition.default_model == "deepseek/model"
    assert definition.capabilities_for_model("deepseek/model")["image_input"] is True

    router = ProviderRouter(settings)
    selection = router.select(body={"input": "hi"}, requested_model="fast")
    assert selection.provider_id == "puter_web"
    assert selection.model == "deepseek/model"
    assert selection.source == "alias"


def test_provider_prefixed_local_alias_resolves_full_alias(monkeypatch, tmp_path):
    settings = _settings(
        monkeypatch,
        tmp_path,
        """
[routing]
default_provider = "nvidia"
[providers.puter_web]
type = "puter_web"
enabled = true
default_model = "real/model"
[providers.puter_web.aliases]
"puter/deepseek-flash" = "real/model"
""",
    )
    router = ProviderRouter(settings)
    selection = router.select(body={"input": "x"}, requested_model="puter/deepseek-flash")
    assert selection.provider_id == "puter_web"
    assert selection.model == "real/model"


def test_legacy_nim_alias_keeps_configured_nvidia_model(monkeypatch, tmp_path):
    monkeypatch.setenv("NVIDIA_NIM_BASE_URL", "https://nvidia.example/v1")
    monkeypatch.setenv("NVIDIA_NIM_API_KEY", "key")
    monkeypatch.setenv("NVIDIA_NIM_MODEL", "configured-nim-model")
    settings = _settings(monkeypatch, tmp_path, "[routing]\ndefault_provider = 'nvidia'\n")
    router = ProviderRouter(settings)
    selection = router.select(body={"messages": []}, requested_model="gpt-4")
    assert selection.provider_id == "nvidia"
    assert selection.model == "configured-nim-model"


def test_image_rejected_when_selected_model_does_not_advertise_it(monkeypatch, tmp_path):
    settings = _settings(
        monkeypatch,
        tmp_path,
        """
[routing]
default_provider = "puter_web"
[providers.puter_web]
type = "puter_web"
enabled = true
default_model = "text-only"
""",
    )
    router = ProviderRouter(settings)
    with pytest.raises(UnsupportedCapabilityError):
        router.select(
            body={"input": [{"type": "input_image", "image_url": "https://example.test/a.png"}]},
            requested_model="text-only",
        )


def test_unknown_explicit_provider_is_not_silently_rewritten(monkeypatch, tmp_path):
    settings = _settings(monkeypatch, tmp_path, "[routing]\ndefault_provider = 'nvidia'\n")
    router = ProviderRouter(settings)
    with pytest.raises(ProviderNotFoundError):
        router.select(body={"provider": "does-not-exist", "messages": []}, requested_model="x")


def test_custom_openai_dispatch_uses_selected_model_not_nim_model(monkeypatch, tmp_path):
    settings = _settings(
        monkeypatch,
        tmp_path,
        """
[routing]
default_provider = "team"
[providers.team]
type = "custom_openai"
enabled = true
base_url = "https://team.example/v1"
api_key_env = "TEAM_KEY"
default_model = "team-default"
""",
    )
    monkeypatch.setenv("TEAM_KEY", "secret")
    sent = {}

    def handler(request):
        import json
        sent["url"] = str(request.url)
        sent["body"] = json.loads(request.content.decode())
        sent["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": "ok"}}]})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            router = ProviderRouter(settings, client)
            selection = router.select(body={"messages": [{"role": "user", "content": "hello"}]}, requested_model="chosen-model")
            result = await router.chat_completion(selection, {"model": "ignored", "messages": [{"role": "user", "content": "hello"}]})
            assert result["choices"][0]["message"]["content"] == "ok"

    asyncio.run(run())
    assert sent["url"] == "https://team.example/v1/chat/completions"
    assert sent["body"]["model"] == "chosen-model"
    assert sent["auth"] == "Bearer secret"
