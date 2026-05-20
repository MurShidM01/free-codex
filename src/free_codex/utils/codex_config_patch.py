"""Patch Free Codex `config.toml` after copying the template."""

DEFAULT_MODEL = "minimaxai/minimax-m2.7"
DEFAULT_PROVIDER_ID = "free_codex_nim"
DEFAULT_PROXY_BASE_URL = "http://127.0.0.1:8080/v1"
DEFAULT_WIRE_API = "responses"


def apply_fc_init_codex_proxy_overrides(
    content: str,
    *,
    model: str = DEFAULT_MODEL,
    model_provider_id: str = DEFAULT_PROVIDER_ID,
    proxy_base_url: str = DEFAULT_PROXY_BASE_URL,
    wire_api: str = DEFAULT_WIRE_API,
) -> str:
    """Force model, model_provider id, provider base_url, and wire_api to proxy defaults.

    Free Codex's preferred client-facing surface is OpenAI's Responses API
    (``POST /v1/responses``). Codex selects that endpoint when the provider
    block declares ``wire_api = "responses"``; the legacy ``"chat"`` value is
    no longer accepted by recent Codex releases. We therefore overwrite any
    existing ``wire_api`` entry and inject one if missing.
    """
    lines = content.splitlines(keepends=True)
    out: list[str] = []
    provider_line = f'model_provider = "{model_provider_id}"'
    wire_api_line = f'wire_api = "{wire_api}"'
    provider_table_header = f"[model_providers.{model_provider_id}]"

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("model =") and not stripped.startswith("model_provider"):
            out.append(f'model = "{model}"\n')
        elif stripped.startswith("model_provider ="):
            out.append(f'{provider_line}\n')
        elif stripped.startswith("base_url ="):
            out.append(f'base_url = "{proxy_base_url}"\n')
        elif stripped.startswith("wire_api ="):
            out.append(f'{wire_api_line}\n')
        else:
            out.append(line)

    patched = "".join(out)

    # Ensure top-level `model_provider = "..."` is present.
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

    # Ensure the provider table contains `wire_api = "responses"`. If a
    # `[model_providers.<id>]` header exists but has no wire_api, inject one
    # immediately after the header line.
    if wire_api_line not in patched and provider_table_header in patched:
        inserted = []
        for line in patched.splitlines(keepends=True):
            inserted.append(line)
            if line.strip() == provider_table_header:
                inserted.append(f"{wire_api_line}\n")
        patched = "".join(inserted)

    return patched
