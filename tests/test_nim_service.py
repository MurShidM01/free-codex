from free_codex.services.nim_service import NIMService
from free_codex.utils.config import ProviderPreset, Settings, TimeoutConfig


def test_thinking_model_detection_includes_glm():
    service = NIMService(client=object())
    assert service._is_thinking_model("glm-5.1")
    assert service._is_thinking_model("deepseek-v4-pro")
    assert service._is_thinking_model("DeepSeek-V4-Pro")


def test_read_timeout_falls_back_to_nim_provider_preset(monkeypatch):
    monkeypatch.delenv("FREE_CODEX_READ_TIMEOUT", raising=False)
    config = Settings()
    assert config.provider_preset == ProviderPreset.NVIDIA_NIM
    assert config.read_timeout == TimeoutConfig.for_preset(ProviderPreset.NVIDIA_NIM).read
