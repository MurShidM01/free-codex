"""Patch Free Codex `config.toml` after copying the template."""

DEFAULT_MODEL = "minimaxai/minimax-m2.7"
DEFAULT_PROVIDER_ID = "free_codex_nim"
DEFAULT_PROXY_BASE_URL = "http://127.0.0.1:8080/v1"


def apply_fc_init_codex_proxy_overrides(
    content: str,
    *,
    model: str = DEFAULT_MODEL,
    model_provider_id: str = DEFAULT_PROVIDER_ID,
    proxy_base_url: str = DEFAULT_PROXY_BASE_URL,
) -> str:
    """Force model, model_provider id, and provider base_url to local proxy defaults."""
    lines = content.splitlines(keepends=True)
    out: list[str] = []
    provider_line = f'model_provider = "{model_provider_id}"'

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("model =") and not stripped.startswith("model_provider"):
            out.append(f'model = "{model}"\n')
        elif stripped.startswith("model_provider ="):
            out.append(f'{provider_line}\n')
        elif stripped.startswith("base_url ="):
            out.append(f'base_url = "{proxy_base_url}"\n')
        else:
            out.append(line)

    patched = "".join(out)
    if provider_line not in patched:
        inserted: list[str] = []
        for line in patched.splitlines(keepends=True):
            inserted.append(line)
            stripped = line.strip()
            if stripped.startswith("model =") and not stripped.startswith(
                "model_provider"
            ):
                inserted.append(f"{provider_line}\n")
        patched = "".join(inserted)

    return patched
