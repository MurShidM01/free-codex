from pathlib import Path

from free_codex.services.admin_env import (
    env_api_payload,
    parse_dotenv_lines,
    validation_errors,
)


def test_validation_requires_nim_keys():
    errs = validation_errors(parse_dotenv_lines("FOO=bar"))
    assert any("NVIDIA_NIM" in e for e in errs)


def test_validation_ok_minimal():
    text = """NVIDIA_NIM_BASE_URL=https://integrate.api.nvidia.com/v1
NVIDIA_NIM_API_KEY=key
NVIDIA_NIM_MODEL=model
"""
    assert validation_errors(parse_dotenv_lines(text)) == []


def test_env_api_masks_without_full_payload():
    raw = "NVIDIA_NIM_API_KEY=secret\n"
    data = env_api_payload(raw_content=raw, reveal_secrets=False)
    assert data["masked"] is True
    assert "***" in data["content"]
