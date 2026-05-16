"""Read/write ~/.config/free-codex/.env with validation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..utils.free_codex_paths import free_codex_dotenv

REQUIRED_NIM_KEYS = (
    "NVIDIA_NIM_BASE_URL",
    "NVIDIA_NIM_API_KEY",
    "NVIDIA_NIM_MODEL",
)


def dotenv_path() -> Path:
    return free_codex_dotenv()


def read_dotenv_file() -> str:
    path = dotenv_path()
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def write_dotenv_file(content: str) -> None:
    path = dotenv_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.rstrip() + "\n", encoding="utf-8")


def parse_dotenv_lines(content: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in content.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if "=" not in s:
            continue
        key, _, val = s.partition("=")
        k = key.strip()
        if not k:
            continue
        v = val.strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
            v = v[1:-1]
        out[k] = v
    return out


def validation_errors(parsed: dict[str, str]) -> list[str]:
    errs: list[str] = []
    for k in REQUIRED_NIM_KEYS:
        if not (parsed.get(k) or "").strip():
            errs.append(f"Missing or empty: {k}")
    url = (parsed.get("NVIDIA_NIM_BASE_URL") or "").strip()
    if url and not (url.startswith("http://") or url.startswith("https://")):
        errs.append("NVIDIA_NIM_BASE_URL must start with http:// or https://")
    return errs


def mask_dotenv_content(content: str) -> str:
    lines: list[str] = []
    for line in content.splitlines():
        stripped = line.strip()
        if "=" in stripped and not stripped.startswith("#"):
            key, _, _ = stripped.partition("=")
            lines.append(f"{key.strip()}=***")
        else:
            lines.append(line)
    return "\n".join(lines)


def env_api_payload(*, raw_content: str, reveal_secrets: bool) -> dict[str, Any]:
    parsed = parse_dotenv_lines(raw_content)
    errs = validation_errors(parsed)
    return {
        "path": str(dotenv_path()),
        "validation_ok": len(errs) == 0,
        "validation_errors": errs,
        "content": raw_content if reveal_secrets else mask_dotenv_content(raw_content),
        "masked": not reveal_secrets,
    }
