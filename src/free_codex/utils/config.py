"""Enhanced configuration management with validation and presets."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

from dotenv import load_dotenv

from .free_codex_paths import free_codex_dotenv


class ProviderPreset(Enum):
    """Pre-configured provider settings."""

    NVIDIA_NIM = "nvidia_nim"
    OLLAMA = "ollama"
    LOCAL = "local"
    CUSTOM = "custom"


@dataclass
class ProviderConfig:
    """Provider-specific configuration."""

    preset: ProviderPreset
    base_url: str
    api_key_env: str
    recommended_model: str
    supports_streaming: bool = True
    supports_tools: bool = True
    supports_embeddings: bool = False
    max_timeout: int = 300


# Pre-configured provider presets
PROVIDER_PRESETS: dict[ProviderPreset, ProviderConfig] = {
    ProviderPreset.NVIDIA_NIM: ProviderConfig(
        preset=ProviderPreset.NVIDIA_NIM,
        base_url="https://integrate.api.nvidia.com/v1",
        api_key_env="NVIDIA_NIM_API_KEY",
        recommended_model="minimaxai/minimax-m2.7",
        supports_streaming=True,
        supports_tools=True,
        supports_embeddings=False,
        max_timeout=600,
    ),
    ProviderPreset.OLLAMA: ProviderConfig(
        preset=ProviderPreset.OLLAMA,
        base_url="http://localhost:11434/v1",
        api_key_env="OLLAMA_API_KEY",
        recommended_model="llama3.2",
        supports_streaming=True,
        supports_tools=True,
        supports_embeddings=True,
        max_timeout=300,
    ),
    ProviderPreset.LOCAL: ProviderConfig(
        preset=ProviderPreset.LOCAL,
        base_url="http://localhost:8080/v1",
        api_key_env="LOCAL_API_KEY",
        recommended_model="auto",
        supports_streaming=True,
        supports_tools=True,
        supports_embeddings=True,
        max_timeout=180,
    ),
}


@dataclass
class TimeoutConfig:
    """Timeout configuration with presets."""

    read: int = 300
    connect: int = 30
    max_retries: int = 3
    heartbeat: int = 25

    @classmethod
    def for_preset(cls, preset: ProviderPreset) -> TimeoutConfig:
        """Get timeout config for a specific provider."""
        configs = {
            ProviderPreset.NVIDIA_NIM: cls(read=600, connect=60, max_retries=4, heartbeat=25),
            ProviderPreset.OLLAMA: cls(read=180, connect=30, max_retries=2, heartbeat=30),
            ProviderPreset.LOCAL: cls(read=120, connect=15, max_retries=1, heartbeat=0),
        }
        return configs.get(preset, cls())


@dataclass
class WorkspaceConfig:
    """Workspace context configuration."""

    enabled: bool = False
    snippet_bytes: int = 65536
    snippet_lines: int = 300
    context_depth: int = 3

    @classmethod
    def from_env(cls) -> WorkspaceConfig:
        """Create from environment variables."""
        return cls(
            enabled=os.getenv("FREE_CODEX_WORKSPACE_CONTEXT", "").strip() == "1",
            snippet_bytes=int(os.getenv("FREE_CODEX_WORKSPACE_SNIPPET_BYTES", "65536")),
            snippet_lines=int(os.getenv("FREE_CODEX_WORKSPACE_SNIPPET_LINES", "300")),
            context_depth=int(os.getenv("FREE_CODEX_WORKSPACE_DEPTH", "3")),
        )


@dataclass
class Settings:
    """Enhanced settings with validation and presets."""

    _cached: dict[str, Any] = field(default_factory=dict)
    _loaded: bool = field(default=False)
    _validation_errors: list[str] = field(default_factory=list)

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        load_dotenv()
        env_path = free_codex_dotenv()
        if env_path.exists():
            load_dotenv(dotenv_path=env_path, override=True)
        self._validate()

    def _validate(self) -> None:
        """Validate required configuration."""
        self._validation_errors = []

        required = [
            ("NVIDIA_NIM_BASE_URL", "NVIDIA_NIM_BASE_URL or NVIDIA_NIM_BASE_URL"),
            ("NVIDIA_NIM_API_KEY", "NVIDIA_NIM_API_KEY"),
        ]

        for key, display_name in required:
            if not os.getenv(key):
                self._validation_errors.append(f"Missing required: {display_name}")

    @property
    def is_valid(self) -> bool:
        """Check if configuration is valid."""
        self._ensure_loaded()
        return len(self._validation_errors) == 0

    @property
    def validation_errors(self) -> list[str]:
        """Get validation errors."""
        self._ensure_loaded()
        return self._validation_errors.copy()

    def _get_env(self, key: str, required: bool = True, default: Any = None) -> Any:
        """Get environment variable with caching."""
        self._ensure_loaded()
        if key in self._cached:
            return self._cached[key]

        val = os.getenv(key)
        if val is None:
            if required and default is None:
                raise ValueError(f"Missing required env var: {key}")
            val = default

        self._cached[key] = val
        return val

    @property
    def server_host(self) -> str:
        return self._get_env("FREE_CODEX_HOST", required=False) or "0.0.0.0"

    @property
    def server_port(self) -> int:
        raw = self._get_env("FREE_CODEX_PORT", required=False)
        try:
            return int(raw) if raw else 8080
        except ValueError:
            return 8080

    @property
    def access_log_requests(self) -> bool:
        v = self._get_env("FREE_CODEX_ACCESS_LOG", required=False) or "0"
        return v.lower() in ("1", "true", "yes")

    # Timeout configuration
    @property
    def read_timeout(self) -> int:
        raw = self._get_env("FREE_CODEX_READ_TIMEOUT", required=False)
        if raw:
            try:
                return int(raw)
            except ValueError:
                pass
        return TimeoutConfig.for_preset(self.provider_preset).read

    @property
    def connect_timeout(self) -> int:
        raw = self._get_env("FREE_CODEX_CONNECT_TIMEOUT", required=False)
        if raw:
            try:
                return int(raw)
            except ValueError:
                pass
        return TimeoutConfig.for_preset(self.provider_preset).connect

    @property
    def max_retries(self) -> int:
        raw = self._get_env("FREE_CODEX_MAX_RETRIES", required=False)
        if raw:
            try:
                return int(raw)
            except ValueError:
                pass
        return TimeoutConfig.for_preset(self.provider_preset).max_retries

    @property
    def sse_heartbeat(self) -> int:
        raw = self._get_env("FREE_CODEX_SSE_HEARTBEAT_SECS", required=False)
        try:
            return int(raw) if raw else 25
        except ValueError:
            return 25

    # Workspace configuration
    @property
    def workspace(self) -> WorkspaceConfig:
        return WorkspaceConfig.from_env()

    # NIM configuration
    @property
    def nim_base_url(self) -> str:
        val = self._get_env("NVIDIA_NIM_BASE_URL", required=False)
        if not val:
            raise ValueError(
                "Missing NVIDIA_NIM_BASE_URL. Run 'fc-init' or configure ~/.config/free-codex/.env"
            )
        return val

    @property
    def nim_api_key(self) -> str:
        val = self._get_env("NVIDIA_NIM_API_KEY", required=False)
        if not val:
            raise ValueError(
                "Missing NVIDIA_NIM_API_KEY. Run 'fc-init' or configure ~/.config/free-codex/.env"
            )
        return val

    @property
    def nim_model(self) -> str:
        val = self._get_env("NVIDIA_NIM_MODEL", required=False)
        if not val:
            raise ValueError(
                "Missing NVIDIA_NIM_MODEL. Run 'fc-init' or configure ~/.config/free-codex/.env"
            )
        return val

    # Provider detection
    @property
    def provider_preset(self) -> ProviderPreset:
        """Detect provider preset based on base URL."""
        base_url = self.nim_base_url.lower()
        if "nvidia" in base_url or "integrate.api.nvidia" in base_url:
            return ProviderPreset.NVIDIA_NIM
        if "localhost" in base_url or "127.0.0.1" in base_url:
            if "11434" in base_url:
                return ProviderPreset.OLLAMA
            return ProviderPreset.LOCAL
        return ProviderPreset.CUSTOM

    @property
    def timeout_config(self) -> TimeoutConfig:
        """Get timeout configuration for current provider."""
        return TimeoutConfig.for_preset(self.provider_preset)

    @property
    def provider_info(self) -> ProviderConfig:
        """Get provider info for current configuration."""
        return PROVIDER_PRESETS.get(self.provider_preset, PROVIDER_PRESETS[ProviderPreset.CUSTOM])

    def reload(self) -> None:
        """Reload environment variables from .env file."""
        self._loaded = False
        self._cached.clear()
        self._validation_errors.clear()

    def to_dict(self) -> dict[str, Any]:
        """Export configuration as dictionary (safe for logging)."""
        self._ensure_loaded()
        return {
            "server": {
                "host": self.server_host,
                "port": self.server_port,
                "log_requests": self.access_log_requests,
            },
            "timeouts": {
                "read": self.read_timeout,
                "connect": self.connect_timeout,
                "max_retries": self.max_retries,
                "heartbeat": self.sse_heartbeat,
            },
            "provider": {
                "preset": self.provider_preset.value,
                "base_url": self.nim_base_url,
                "model": self.nim_model,
            },
            "workspace": {
                "enabled": self.workspace.enabled,
                "snippet_bytes": self.workspace.snippet_bytes,
                "snippet_lines": self.workspace.snippet_lines,
            },
            "is_valid": self.is_valid,
            "validation_errors": self.validation_errors,
        }


settings = Settings()