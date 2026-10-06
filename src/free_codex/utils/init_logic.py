"""fc-init setup for the stable local Codex endpoint and provider router."""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

from .codex_config_patch import apply_fc_init_codex_proxy_overrides
from .free_codex_paths import (
    free_codex_config_toml,
    free_codex_dir,
    free_codex_dotenv,
    free_codex_providers_toml,
)

_FALLBACK_DEFAULT_MODEL = "minimaxai/minimax-m2.7"

_FALLBACK_CODEX_TOML = f"""#:schema https://developers.openai.com/codex/config-schema.json

model = "{_FALLBACK_DEFAULT_MODEL}"
model_provider = "free_codex_nim"

[model_providers.free_codex_nim]
name = "Free Codex (local OmniRoute proxy)"
base_url = "http://127.0.0.1:8080/v1"
wire_api = "responses"

[windows]
sandbox = "elevated"
"""


def _codex_config_path() -> Path:
    return Path.home() / ".codex" / "config.toml"


def _canonical_provider(provider: str) -> str:
    raw = (provider or "nvidia").strip().lower().replace("-", "_")
    return {
        "nvidia_nim": "nvidia",
        "nim": "nvidia",
        "puter": "puter_web",
        "custom": "custom_openai",
        "openai": "custom_openai",
    }.get(raw, raw)


def routed_model(provider: str, model: str) -> str:
    """Encode a process-local provider choice in the model field.

    Codex has no request-header setting for a local provider selection. The
    router recognizes ``provider:model`` and strips the prefix before dispatch;
    Codex still talks only to the same local base URL.
    """
    canonical = _canonical_provider(provider)
    if canonical in ("", "nvidia"):
        return model
    return "{0}:{1}".format(canonical, model)


def _set_env_values(path: Path, values: dict[str, str]) -> None:
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    lines = existing.splitlines()
    pending = dict(values)
    output = []
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in line:
            key = line.split("=", 1)[0].strip()
            if key in pending:
                output.append("{0}={1}".format(key, pending.pop(key)))
                continue
        output.append(line)
    if pending:
        if output and output[-1] != "":
            output.append("")
        output.append("# Selected by fc-init")
        output.extend("{0}={1}".format(key, value) for key, value in pending.items())
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(output).rstrip() + "\n", encoding="utf-8")


def _apply_provider_choice(env_path: Path, provider: str, model: Optional[str]) -> str:
    canonical = _canonical_provider(provider)
    values = {"FREE_CODEX_DEFAULT_PROVIDER": canonical}
    default_model = model or ""
    if canonical == "nvidia":
        if default_model:
            values["NVIDIA_NIM_MODEL"] = default_model
    elif canonical == "ollama":
        values["OLLAMA_ENABLED"] = "1"
        values["OLLAMA_MODEL"] = default_model or os.getenv("OLLAMA_MODEL", "") or "llama3.2"
    elif canonical == "local":
        values["LOCAL_OPENAI_ENABLED"] = "1"
        if default_model:
            values["LOCAL_OPENAI_MODEL"] = default_model
    elif canonical == "custom_openai":
        values["CUSTOM_OPENAI_ENABLED"] = "1"
        if default_model:
            values["CUSTOM_OPENAI_MODEL"] = default_model
    elif canonical == "puter_web":
        values["PUTER_WEB_ENABLED"] = "1"
        values["PUTER_WEB_MODEL"] = default_model or os.getenv("PUTER_WEB_MODEL", "") or "deepseek/deepseek-v4.1-flash"
    else:
        raise ValueError("Unknown provider: {0}".format(provider))
    _set_env_values(env_path, values)
    return canonical


def _interactive_choice() -> tuple[str, Optional[str]]:
    options = [
        ("nvidia", "NVIDIA NIM / existing compatible setup"),
        ("ollama", "Ollama local server"),
        ("local", "local OpenAI-compatible server"),
        ("custom_openai", "custom OpenAI-compatible endpoint"),
        ("puter_web", "Puter Web through official Puter.js browser bridge"),
    ]
    print("Select a Free Codex upstream provider:")
    for index, (_, label) in enumerate(options, start=1):
        print("  {0}. {1}".format(index, label))
    raw = input("Provider [1]: ").strip() or "1"
    try:
        provider = options[int(raw) - 1][0]
    except (ValueError, IndexError):
        raise ValueError("Invalid provider selection")
    model = input("Model (leave empty to use configured default): ").strip() or None
    return provider, model


def fc_init(
    *,
    provider: Optional[str] = None,
    model: Optional[str] = None,
    interactive: bool = False,
) -> None:
    """Initialize config without changing Codex's stable local base URL."""
    root = free_codex_dir()
    root.mkdir(parents=True, exist_ok=True)
    package_dir = Path(__file__).parent.parent
    config_dst = free_codex_config_toml()
    env_dst = free_codex_dotenv()
    providers_dst = free_codex_providers_toml()

    env_src = package_dir / "config" / "env.example"
    env_copied = False
    if not env_dst.exists() and env_src.exists():
        shutil.copy(env_src, env_dst)
        print("Copied .env template to {0}".format(env_dst))
        env_copied = True
    if env_dst.exists() and not env_copied:
        print(".env already exists at {0} — skipping .env init.".format(env_dst))

    providers_src = package_dir / "config" / "providers.toml.example"
    if not providers_dst.exists() and providers_src.exists():
        shutil.copy(providers_src, providers_dst)
        print("Initialized provider router config at {0}".format(providers_dst))

    if interactive and provider is None:
        provider, model = _interactive_choice()
    selected_provider = "nvidia"
    if provider:
        selected_provider = _apply_provider_choice(env_dst, provider, model)
        print("Selected provider '{0}' for this Free Codex configuration.".format(selected_provider))

    if env_dst.exists():
        load_dotenv(dotenv_path=env_dst, override=True)

    # Preserve existing NIM defaults when no new provider choice is supplied.
    if model:
        model_slug = model.strip()
    elif selected_provider == "puter_web":
        model_slug = (os.getenv("PUTER_WEB_MODEL") or "deepseek/deepseek-v4.1-flash").strip()
    elif selected_provider == "ollama":
        model_slug = (os.getenv("OLLAMA_MODEL") or "llama3.2").strip()
    elif selected_provider == "local":
        model_slug = (os.getenv("LOCAL_OPENAI_MODEL") or "auto").strip()
    elif selected_provider == "custom_openai":
        model_slug = (os.getenv("CUSTOM_OPENAI_MODEL") or "auto").strip()
    else:
        model_slug = (os.getenv("NVIDIA_NIM_MODEL") or _FALLBACK_DEFAULT_MODEL).strip()
    if not model_slug:
        model_slug = _FALLBACK_DEFAULT_MODEL
    codex_model = routed_model(selected_provider, model_slug)

    config_copied = False
    if not config_dst.exists():
        config_src = package_dir / "config" / "config.toml.example"
        if config_src.exists():
            shutil.copy(config_src, config_dst)
            print("Initialized Codex config at {0}".format(config_dst))
            config_copied = True
        else:
            config_dst.write_text(_FALLBACK_CODEX_TOML, encoding="utf-8")
            print("Created default Codex config at {0}".format(config_dst))
            config_copied = True

    if not config_copied:
        print("config.toml already exists at {0} — retaining custom settings.".format(config_dst))

    codex_config = _codex_config_path()
    if config_dst.exists():
        raw = config_dst.read_text(encoding="utf-8")
        config_dst.write_text(
            apply_fc_init_codex_proxy_overrides(raw, model=codex_model), encoding="utf-8"
        )
        print("Set Codex model to {0!r}; upstream routing remains local in {1}".format(codex_model, config_dst))
        try:
            codex_config.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(config_dst, codex_config)
            print("Updated Codex extension config at {0}".format(codex_config))
        except Exception as exc:
            print("Note: could not copy VS Code extension config: {0}".format(exc))

    if selected_provider == "puter_web":
        print("Puter Web uses a hidden browser bridge after one-time login: run fc-puter-auth.")
    print("Codex will use CODEX_HOME={0} when launched via fc-codex.".format(root.resolve()))
