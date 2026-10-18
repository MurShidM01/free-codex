"""Launch Codex CLI against the one stable Free Codex local base URL."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import List, Optional, Tuple

from .utils.codex_config_patch import apply_fc_init_codex_proxy_overrides
from .utils.free_codex_paths import (
    default_server_health_url,
    free_codex_config_toml,
    free_codex_dir,
)
from .utils.init_logic import routed_model


def resolve_codex_executable() -> Optional[str]:
    return shutil.which("codex")


def _proxy_healthy(url: str, timeout: float = 2.0) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            if resp.getcode() != 200:
                return False
            data = json.loads(resp.read().decode("utf-8"))
            return data.get("status") == "healthy"
    except (OSError, urllib.error.URLError, json.JSONDecodeError, ValueError):
        return False


def _canonical_provider(value: str) -> str:
    raw = (value or "").strip().lower().replace("-", "_")
    return {"nim": "nvidia", "nvidia_nim": "nvidia", "puter": "puter_web", "custom": "custom_openai"}.get(raw, raw)


def _extract_routing_flags(args: List[str]) -> Tuple[Optional[str], Optional[str], List[str]]:
    provider = None
    model = None
    rest: List[str] = []
    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--provider" and i + 1 < len(args):
            provider = args[i + 1]
            i += 2
            continue
        if arg.startswith("--provider="):
            provider = arg.split("=", 1)[1]
            i += 1
            continue
        if arg == "--model" and i + 1 < len(args):
            model = args[i + 1]
            i += 2
            continue
        if arg.startswith("--model="):
            model = arg.split("=", 1)[1]
            i += 1
            continue
        rest.append(arg)
        i += 1
    return provider, model, rest


def _provider_preflight(health_url: str, provider: str, timeout: float = 3.0) -> Tuple[bool, str]:
    """Check selected Puter state without exposing browser credentials."""
    try:
        base = health_url.rsplit("/health/json", 1)[0]
        url = base + "/v1/providers/" + provider
        with urllib.request.urlopen(url, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
        health = data.get("health") or {}
        if health.get("ready"):
            return True, ""
        status = health.get("status") or "unavailable"
        if status == "authentication_required":
            return False, "Puter Web needs one-time authentication. Run fc-puter-auth, then retry fc-codex."
        message = health.get("message") or "Puter Web is not initialized; run fc-puter-auth."
        return False, str(message)
    except (OSError, urllib.error.URLError, ValueError, json.JSONDecodeError):
        return False, "Could not preflight Puter Web. Ensure fc-server is running, then run fc-puter-auth if needed."


def _default_model_for_provider(provider: str) -> str:
    canonical = _canonical_provider(provider)
    mapping = {
        "nvidia": os.getenv("NVIDIA_NIM_MODEL", ""),
        "ollama": os.getenv("OLLAMA_MODEL", ""),
        "local": os.getenv("LOCAL_OPENAI_MODEL", ""),
        "custom_openai": os.getenv("CUSTOM_OPENAI_MODEL", ""),
        "puter_web": os.getenv("PUTER_WEB_MODEL", ""),
    }
    return mapping.get(canonical, "") or "auto"


def _temporary_codex_home(config_path: Path, model: str):
    """Return a TemporaryDirectory and config home with a process-only model."""
    temp = tempfile.TemporaryDirectory(prefix="free-codex-")
    root = Path(temp.name)
    raw = config_path.read_text(encoding="utf-8")
    (root / "config.toml").write_text(
        apply_fc_init_codex_proxy_overrides(raw, model=model), encoding="utf-8"
    )
    return temp, root


def run_codex() -> None:
    cfg = free_codex_config_toml()
    if not cfg.is_file():
        print("Error: missing {0}. Run fc-init first.".format(cfg))
        sys.exit(2)

    provider, selected_model, codex_args = _extract_routing_flags(list(sys.argv[1:]))
    health_url = os.getenv("FREE_CODEX_HEALTH_URL") or default_server_health_url()
    if not _proxy_healthy(health_url):
        print(
            "Error: fc-server is not running or not reachable at {0}. "
            "Start fc-server first (match FREE_CODEX_PORT if set).".format(health_url)
        )
        sys.exit(3)

    canonical_provider = _canonical_provider(provider or "")
    if canonical_provider == "puter_web":
        ready, message = _provider_preflight(health_url, canonical_provider)
        if not ready:
            print("Error: {0}".format(message))
            sys.exit(4)

    codex = resolve_codex_executable()
    if not codex:
        print("Error: 'codex' command not found. Install the OpenAI Codex CLI.")
        sys.exit(1)

    env = os.environ.copy()
    temp = None
    if provider or selected_model:
        chosen_provider = canonical_provider or "nvidia"
        upstream_model = selected_model or _default_model_for_provider(chosen_provider)
        # A prefixed local routing model is consumed by Free Codex; no upstream
        # URL/key reaches Codex config and the source config is never mutated.
        local_model = routed_model(chosen_provider, upstream_model)
        temp, home = _temporary_codex_home(cfg, local_model)
        env["CODEX_HOME"] = str(home.resolve())
        print("Free Codex session route: provider={0}, model={1}".format(chosen_provider, upstream_model), flush=True)
    else:
        env["CODEX_HOME"] = str(free_codex_dir().resolve())

    try:
        proc = subprocess.Popen([codex, *codex_args], env=env)
        try:
            rc = proc.wait()
        except KeyboardInterrupt:
            proc.terminate()
            try:
                proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=3)
            sys.exit(130)
        sys.exit(rc)
    finally:
        if temp is not None:
            temp.cleanup()
