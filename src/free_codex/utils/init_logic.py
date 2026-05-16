import os
import shutil
from pathlib import Path

from dotenv import load_dotenv

from .codex_config_patch import apply_fc_init_codex_proxy_overrides
from .free_codex_paths import free_codex_config_toml, free_codex_dir, free_codex_dotenv

_FALLBACK_DEFAULT_MODEL = "minimaxai/minimax-m2.7"

# Shipped if config/config.toml.example is missing (e.g. broken wheel layout).
_FALLBACK_CODEX_TOML = f"""#:schema https://developers.openai.com/codex/config-schema.json

model = "{_FALLBACK_DEFAULT_MODEL}"
model_provider = "free_codex_nim"

[model_providers.free_codex_nim]
name = "Free Codex (local NIM proxy)"
base_url = "http://127.0.0.1:8080/v1"

[windows]
sandbox = "elevated"
"""


def fc_init() -> None:
    root = free_codex_dir()
    root.mkdir(parents=True, exist_ok=True)

    package_dir = Path(__file__).parent.parent
    config_dst = free_codex_config_toml()
    env_dst = free_codex_dotenv()

    # Only copy .env template if it doesn't exist
    env_src = package_dir / "config" / "env.example"
    env_copied = False
    if not env_dst.exists():
        if env_src.exists():
            shutil.copy(env_src, env_dst)
            print(f"Copied .env template to {env_dst}")
            env_copied = True
    if env_dst.exists() and not env_copied:
        print(f".env already exists at {env_dst} — skipping .env init.")

    if env_dst.exists():
        load_dotenv(dotenv_path=env_dst, override=True)

    model_slug = (os.getenv("NVIDIA_NIM_MODEL") or _FALLBACK_DEFAULT_MODEL).strip()
    if not model_slug:
        model_slug = _FALLBACK_DEFAULT_MODEL

    # Only initialize config.toml if it doesn't exist
    config_copied = False
    if not config_dst.exists():
        config_src = package_dir / "config" / "config.toml.example"
        if config_src.exists():
            shutil.copy(config_src, config_dst)
            print(f"Initialized Codex config at {config_dst}")
            config_copied = True
        else:
            config_dst.write_text(_FALLBACK_CODEX_TOML, encoding="utf-8")
            print(f"Created default Codex config at {config_dst}")
            config_copied = True

    if not config_copied:
        print(f"config.toml already exists at {config_dst} — skipping config init.")
        print("To re-initialize, delete the file and run fc-init again.")
        print(f"Codex will use CODEX_HOME={root.resolve()} when launched via fc-codex.")
        return

    if config_dst.exists():
        raw = config_dst.read_text(encoding="utf-8")
        config_dst.write_text(
            apply_fc_init_codex_proxy_overrides(raw, model=model_slug),
            encoding="utf-8",
        )
        print(
            f"Set Codex model to {model_slug!r} and proxy provider in {config_dst}"
        )

    print("Codex will use CODEX_HOME=" + str(root.resolve()) + " when launched via fc-codex.")
