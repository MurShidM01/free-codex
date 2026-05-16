import pytest


@pytest.fixture(autouse=True)
def _default_nim_env(monkeypatch):
    """Routes read os.getenv at request time; ensure tests never lack NIM vars."""
    monkeypatch.setenv("NVIDIA_NIM_BASE_URL", "https://test.nim.example/v1")
    monkeypatch.setenv("NVIDIA_NIM_API_KEY", "test-nim-key")
    monkeypatch.setenv("NVIDIA_NIM_MODEL", "test-model")
