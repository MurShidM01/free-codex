"""Configuration for the local, provider-neutral Free Codex router.

Legacy ``NVIDIA_NIM_*`` values remain first-class inputs.  Multi-provider
configuration lives in ``providers.toml`` (or ``FREE_CODEX_PROVIDERS_CONFIG``)
and is intentionally separate from Codex's generated ``config.toml``.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv

from .free_codex_paths import free_codex_dotenv, free_codex_providers_toml

try:  # Python 3.11+
    import tomllib  # type: ignore
except ModuleNotFoundError:  # pragma: no cover - exercised on Python 3.9/3.10
    import tomli as tomllib  # type: ignore


class ProviderPreset(Enum):
    """Historical provider presets kept for callers of the original API."""

    NVIDIA_NIM = "nvidia_nim"
    OLLAMA = "ollama"
    LOCAL = "local"
    CUSTOM = "custom"
    CUSTOM_OPENAI = "custom_openai"
    PUTER_WEB = "puter_web"


class ProviderType(str, Enum):
    """Canonical internal provider types."""

    NVIDIA_NIM = "nvidia_nim"
    OLLAMA = "ollama"
    LOCAL = "local"
    CUSTOM_OPENAI = "custom_openai"
    PUTER_WEB = "puter_web"

    @classmethod
    def normalize(cls, value: Any) -> "ProviderType":
        raw = str(value or "custom_openai").strip().lower().replace("-", "_")
        aliases = {
            "nvidia": cls.NVIDIA_NIM.value,
            "nim": cls.NVIDIA_NIM.value,
            "openai": cls.CUSTOM_OPENAI.value,
            "custom": cls.CUSTOM_OPENAI.value,
            "openai_compatible": cls.CUSTOM_OPENAI.value,
            "puter": cls.PUTER_WEB.value,
            "puterweb": cls.PUTER_WEB.value,
        }
        raw = aliases.get(raw, raw)
        try:
            return cls(raw)
        except ValueError:
            return cls.CUSTOM_OPENAI


@dataclass
class ProviderConfig:
    """Provider-specific preset metadata (backward compatible public type)."""

    preset: ProviderPreset
    base_url: str
    api_key_env: str
    recommended_model: str
    supports_streaming: bool = True
    supports_tools: bool = True
    supports_embeddings: bool = False
    max_timeout: int = 300


@dataclass
class ProviderDefinition:
    """A configured router provider, with no secret values in ``to_dict``."""

    id: str
    type: ProviderType
    enabled: bool = False
    base_url: str = ""
    api_key_env: str = ""
    api_key: str = ""
    default_model: str = ""
    model_aliases: Dict[str, str] = field(default_factory=dict)
    model_capabilities: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    capabilities: Dict[str, Any] = field(default_factory=dict)
    max_concurrent_requests: int = 0
    options: Dict[str, Any] = field(default_factory=dict)

    def resolve_api_key(self) -> str:
        if self.api_key:
            return self.api_key
        if self.api_key_env:
            return os.getenv(self.api_key_env, "")
        return ""

    def resolve_model(self, model: str) -> str:
        requested = (model or "").strip()
        return self.model_aliases.get(requested, requested or self.default_model)

    def capabilities_for_model(self, model: str) -> Dict[str, Any]:
        selected = self.resolve_model(model)
        result = dict(self.capabilities)
        # Both raw model IDs and friendly aliases may have an override.
        for key in (model, selected):
            override = self.model_capabilities.get(key)
            if isinstance(override, dict):
                result.update(override)
        return result

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type.value,
            "enabled": self.enabled,
            "configured": bool(self.base_url or self.type == ProviderType.PUTER_WEB),
            "base_url": self.base_url,
            "api_key_configured": bool(self.resolve_api_key()),
            "default_model": self.default_model,
            "model_aliases": dict(self.model_aliases),
            "capabilities": dict(self.capabilities),
            "model_capabilities": dict(self.model_capabilities),
            "max_concurrent_requests": self.max_concurrent_requests,
        }


@dataclass
class RoutingConfig:
    default_provider: str = "nvidia"
    model_routes: Dict[str, str] = field(default_factory=dict)
    aliases: Dict[str, str] = field(default_factory=dict)
    fallback_providers: List[str] = field(default_factory=list)
    sticky_sessions: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "default_provider": self.default_provider,
            "model_routes": dict(self.model_routes),
            "aliases": dict(self.aliases),
            "fallback_providers": list(self.fallback_providers),
            "sticky_sessions": self.sticky_sessions,
        }


# Pre-configured provider presets
PROVIDER_PRESETS: Dict[ProviderPreset, ProviderConfig] = {
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
        base_url="http://127.0.0.1:11434/v1",
        api_key_env="OLLAMA_API_KEY",
        recommended_model="llama3.2",
        supports_streaming=True,
        supports_tools=True,
        supports_embeddings=True,
        max_timeout=300,
    ),
    ProviderPreset.LOCAL: ProviderConfig(
        preset=ProviderPreset.LOCAL,
        base_url="http://127.0.0.1:8000/v1",
        api_key_env="LOCAL_OPENAI_API_KEY",
        recommended_model="auto",
        supports_streaming=True,
        supports_tools=True,
        supports_embeddings=True,
        max_timeout=180,
    ),
    ProviderPreset.CUSTOM: ProviderConfig(
        preset=ProviderPreset.CUSTOM,
        base_url="",
        api_key_env="CUSTOM_OPENAI_API_KEY",
        recommended_model="",
    ),
    ProviderPreset.CUSTOM_OPENAI: ProviderConfig(
        preset=ProviderPreset.CUSTOM_OPENAI,
        base_url="",
        api_key_env="CUSTOM_OPENAI_API_KEY",
        recommended_model="",
    ),
    ProviderPreset.PUTER_WEB: ProviderConfig(
        preset=ProviderPreset.PUTER_WEB,
        base_url="",
        api_key_env="",
        recommended_model="",
        supports_embeddings=False,
        max_timeout=900,
    ),
}


@dataclass
class TimeoutConfig:
    read: int = 300
    connect: int = 30
    max_retries: int = 3
    heartbeat: int = 25

    @classmethod
    def for_preset(cls, preset: ProviderPreset) -> "TimeoutConfig":
        configs = {
            ProviderPreset.NVIDIA_NIM: cls(read=600, connect=60, max_retries=4, heartbeat=25),
            ProviderPreset.OLLAMA: cls(read=180, connect=30, max_retries=2, heartbeat=30),
            ProviderPreset.LOCAL: cls(read=120, connect=15, max_retries=1, heartbeat=0),
            ProviderPreset.PUTER_WEB: cls(read=900, connect=30, max_retries=1, heartbeat=20),
        }
        return configs.get(preset, cls())


@dataclass
class WorkspaceConfig:
    enabled: bool = False
    snippet_bytes: int = 65536
    snippet_lines: int = 300
    context_depth: int = 3

    @classmethod
    def from_env(cls) -> "WorkspaceConfig":
        return cls(
            enabled=_bool_env("FREE_CODEX_WORKSPACE_CONTEXT", False),
            snippet_bytes=_int_env("FREE_CODEX_WORKSPACE_SNIPPET_BYTES", 65536),
            snippet_lines=_int_env("FREE_CODEX_WORKSPACE_SNIPPET_LINES", 300),
            context_depth=_int_env("FREE_CODEX_WORKSPACE_DEPTH", 3),
        )


def _bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def _bool_env(key: str, default: bool = False) -> bool:
    raw = os.getenv(key)
    return _bool(raw, default) if raw is not None else default


def _int_env(key: str, default: int) -> int:
    raw = os.getenv(key)
    try:
        return int(raw) if raw not in (None, "") else default
    except (TypeError, ValueError):
        return default


def _json_mapping(raw: str) -> Dict[str, Any]:
    if not raw:
        return {}
    try:
        val = json.loads(raw)
        return val if isinstance(val, dict) else {}
    except (TypeError, ValueError):
        return {}


def _normalise_url(value: Any) -> str:
    return str(value or "").strip().rstrip("/")


@dataclass
class Settings:
    """Environment and TOML-backed settings.

    The object is intentionally lazy so test suites and the admin editor can
    change environment variables then call :meth:`reload` without restarting.
    """

    _cached: Dict[str, Any] = field(default_factory=dict)
    _loaded: bool = field(default=False)
    _validation_errors: List[str] = field(default_factory=list)
    _provider_definitions: Optional[Dict[str, ProviderDefinition]] = field(default=None)
    _routing: Optional[RoutingConfig] = field(default=None)

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
        self._validation_errors = []
        # Do not make every installation configure NIM: Puter, Ollama, and
        # custom routes are valid first-class defaults.  Preserve NIM errors
        # when NIM remains the selected legacy default.
        config_default = ""
        try:
            raw_root = self._load_provider_toml()
            raw_routing = raw_root.get("routing", {}) if isinstance(raw_root, dict) else {}
            if isinstance(raw_routing, dict):
                config_default = str(raw_routing.get("default_provider") or "")
        except Exception:
            config_default = ""
        default = (os.getenv("FREE_CODEX_DEFAULT_PROVIDER") or config_default or "nvidia").strip()
        if ProviderType.normalize(default) == ProviderType.NVIDIA_NIM:
            if not os.getenv("NVIDIA_NIM_BASE_URL"):
                self._validation_errors.append("Missing required: NVIDIA_NIM_BASE_URL")
            if not os.getenv("NVIDIA_NIM_API_KEY"):
                self._validation_errors.append("Missing required: NVIDIA_NIM_API_KEY")

    @property
    def is_valid(self) -> bool:
        self._ensure_loaded()
        return not self._validation_errors

    @property
    def validation_errors(self) -> List[str]:
        self._ensure_loaded()
        return list(self._validation_errors)

    def _get_env(self, key: str, required: bool = True, default: Any = None) -> Any:
        self._ensure_loaded()
        if key in self._cached:
            return self._cached[key]
        val = os.getenv(key)
        if val is None:
            if required and default is None:
                raise ValueError("Missing required env var: {0}".format(key))
            val = default
        self._cached[key] = val
        return val

    @property
    def server_host(self) -> str:
        return self._get_env("FREE_CODEX_HOST", required=False) or "0.0.0.0"

    @property
    def server_port(self) -> int:
        return _int_env("FREE_CODEX_PORT", 8080)

    @property
    def access_log_requests(self) -> bool:
        return _bool_env("FREE_CODEX_ACCESS_LOG", False)

    @property
    def debug_provider_payloads(self) -> bool:
        """Explicit opt-in only; logging still redacts credentials/cookies."""
        return _bool_env("FREE_CODEX_DEBUG_PROVIDER_PAYLOADS", False)

    @property
    def read_timeout(self) -> int:
        raw = self._get_env("FREE_CODEX_READ_TIMEOUT", required=False)
        if raw:
            try:
                return int(raw)
            except (TypeError, ValueError):
                pass
        return TimeoutConfig.for_preset(self.provider_preset).read

    @property
    def connect_timeout(self) -> int:
        raw = self._get_env("FREE_CODEX_CONNECT_TIMEOUT", required=False)
        if raw:
            try:
                return int(raw)
            except (TypeError, ValueError):
                pass
        return TimeoutConfig.for_preset(self.provider_preset).connect

    @property
    def max_retries(self) -> int:
        raw = self._get_env("FREE_CODEX_MAX_RETRIES", required=False)
        if raw:
            try:
                return int(raw)
            except (TypeError, ValueError):
                pass
        return TimeoutConfig.for_preset(self.provider_preset).max_retries

    @property
    def sse_heartbeat(self) -> int:
        return _int_env("FREE_CODEX_SSE_HEARTBEAT_SECS", 25)

    @property
    def workspace(self) -> WorkspaceConfig:
        return WorkspaceConfig.from_env()

    # --- Legacy NIM properties.  Existing code and existing .env files use these. ---
    @property
    def nim_base_url(self) -> str:
        val = self._get_env("NVIDIA_NIM_BASE_URL", required=False)
        if not val:
            raise ValueError(
                "Missing NVIDIA_NIM_BASE_URL. Run 'fc-init' or configure ~/.config/free-codex/.env"
            )
        return _normalise_url(val)

    @property
    def nim_api_key(self) -> str:
        val = self._get_env("NVIDIA_NIM_API_KEY", required=False)
        if not val:
            raise ValueError(
                "Missing NVIDIA_NIM_API_KEY. Run 'fc-init' or configure ~/.config/free-codex/.env"
            )
        return str(val)

    @property
    def nim_model(self) -> str:
        val = self._get_env("NVIDIA_NIM_MODEL", required=False)
        if not val:
            raise ValueError(
                "Missing NVIDIA_NIM_MODEL. Run 'fc-init' or configure ~/.config/free-codex/.env"
            )
        return str(val)

    @property
    def provider_preset(self) -> ProviderPreset:
        """Legacy base-URL detection used by timeout tests and NIM service."""
        try:
            base_url = self.nim_base_url.lower()
        except ValueError:
            selected = self.default_provider_type
            if selected == ProviderType.PUTER_WEB:
                return ProviderPreset.PUTER_WEB
            if selected == ProviderType.OLLAMA:
                return ProviderPreset.OLLAMA
            if selected == ProviderType.LOCAL:
                return ProviderPreset.LOCAL
            return ProviderPreset.CUSTOM
        if "localhost" in base_url or "127.0.0.1" in base_url:
            if "11434" in base_url:
                return ProviderPreset.OLLAMA
            return ProviderPreset.LOCAL
        # NVIDIA_NIM_* was historically also the generic compatible-endpoint
        # configuration. Keep its long NIM timeout preset for any non-local
        # legacy URL; first-class custom providers use CUSTOM_OPENAI_* instead.
        return ProviderPreset.NVIDIA_NIM

    @property
    def timeout_config(self) -> TimeoutConfig:
        return TimeoutConfig.for_preset(self.provider_preset)

    @property
    def provider_info(self) -> ProviderConfig:
        return PROVIDER_PRESETS.get(self.provider_preset, PROVIDER_PRESETS[ProviderPreset.CUSTOM])

    # --- New multi-provider settings ---
    @property
    def providers_config_path(self) -> Path:
        raw = os.getenv("FREE_CODEX_PROVIDERS_CONFIG", "").strip()
        return Path(raw).expanduser() if raw else free_codex_providers_toml()

    def _load_provider_toml(self) -> Dict[str, Any]:
        path = self.providers_config_path
        if not path.is_file():
            return {}
        try:
            with path.open("rb") as handle:
                value = tomllib.load(handle)
            return value if isinstance(value, dict) else {}
        except (OSError, ValueError, tomllib.TOMLDecodeError) as exc:  # type: ignore[attr-defined]
            # Bad optional routing config should not stop legacy NIM service.
            self._validation_errors.append("Could not read providers config: {0}".format(exc))
            return {}

    def _builtin_definitions(self) -> Dict[str, ProviderDefinition]:
        nvidia_enabled = _bool_env(
            "NVIDIA_NIM_ENABLED",
            bool(os.getenv("NVIDIA_NIM_BASE_URL") or os.getenv("NVIDIA_NIM_MODEL")),
        )
        nvidia = ProviderDefinition(
            id="nvidia",
            type=ProviderType.NVIDIA_NIM,
            enabled=nvidia_enabled,
            base_url=_normalise_url(os.getenv("NVIDIA_NIM_BASE_URL", "")),
            api_key_env="NVIDIA_NIM_API_KEY",
            default_model=os.getenv("NVIDIA_NIM_MODEL", "").strip(),
            capabilities={
                "text_input": True,
                "streaming": True,
                "tool_calling": True,
                "parallel_tool_calls": True,
                "structured_output": True,
                "reasoning": True,
                "provider_notes": "OpenAI-compatible NVIDIA NIM transport.",
            },
        )
        ollama = ProviderDefinition(
            id="ollama",
            type=ProviderType.OLLAMA,
            enabled=_bool_env("OLLAMA_ENABLED", False),
            base_url=_normalise_url(os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434/v1")),
            api_key_env="OLLAMA_API_KEY",
            default_model=os.getenv("OLLAMA_MODEL", "").strip(),
            capabilities={
                "text_input": True,
                "streaming": True,
                "tool_calling": True,
                "parallel_tool_calls": False,
                "structured_output": False,
                "provider_notes": "Capabilities vary by installed Ollama model.",
            },
        )
        local = ProviderDefinition(
            id="local",
            type=ProviderType.LOCAL,
            enabled=_bool_env("LOCAL_OPENAI_ENABLED", False),
            base_url=_normalise_url(os.getenv("LOCAL_OPENAI_BASE_URL", "")),
            api_key_env="LOCAL_OPENAI_API_KEY",
            default_model=os.getenv("LOCAL_OPENAI_MODEL", "").strip(),
            capabilities={
                "text_input": True,
                "streaming": True,
                "tool_calling": True,
                "provider_notes": "OpenAI-compatible local endpoint.",
            },
        )
        custom = ProviderDefinition(
            id="custom_openai",
            type=ProviderType.CUSTOM_OPENAI,
            enabled=_bool_env("CUSTOM_OPENAI_ENABLED", False),
            base_url=_normalise_url(os.getenv("CUSTOM_OPENAI_BASE_URL", "")),
            api_key_env="CUSTOM_OPENAI_API_KEY",
            default_model=os.getenv("CUSTOM_OPENAI_MODEL", "").strip(),
            capabilities={
                "text_input": True,
                "streaming": True,
                "tool_calling": True,
                "provider_notes": "Configured OpenAI-compatible endpoint.",
            },
        )
        puter = ProviderDefinition(
            id="puter_web",
            type=ProviderType.PUTER_WEB,
            enabled=_bool_env("PUTER_WEB_ENABLED", False),
            default_model=os.getenv("PUTER_WEB_MODEL", "").strip(),
            max_concurrent_requests=max(0, _int_env("PUTER_WEB_MAX_CONCURRENT_REQUESTS", 1)),
            capabilities={
                "text_input": True,
                "streaming": True,
                "tool_calling": True,
                "parallel_tool_calls": True,
                "structured_output": False,
                "reasoning": False,
                "provider_notes": (
                    "Browser-mediated through official Puter.js. Image/video support is "
                    "disabled unless a model-specific capability override enables it."
                ),
            },
            options={
                "browser": os.getenv("PUTER_WEB_BROWSER", "chromium"),
                "headless": _bool_env("PUTER_WEB_HEADLESS", True),
                "profile_dir": os.getenv("PUTER_WEB_PROFILE_DIR", "").strip(),
                "auth_timeout": _int_env("PUTER_WEB_AUTH_TIMEOUT", 300),
                "connect_timeout": _int_env("PUTER_WEB_CONNECT_TIMEOUT", 30),
                "session_timeout": _int_env("PUTER_WEB_SESSION_TIMEOUT", 3600),
                "request_timeout": _int_env("PUTER_WEB_REQUEST_TIMEOUT", 900),
            },
        )
        return {x.id: x for x in (nvidia, ollama, local, custom, puter)}

    @staticmethod
    def _provider_from_mapping(
        provider_id: str,
        raw: Dict[str, Any],
        fallback: Optional[ProviderDefinition] = None,
    ) -> ProviderDefinition:
        base = fallback or ProviderDefinition(
            id=provider_id,
            type=ProviderType.CUSTOM_OPENAI,
            enabled=True,
        )
        type_value = raw.get("type", raw.get("provider", base.type.value))
        ptype = ProviderType.normalize(type_value)
        aliases = raw.get("aliases", raw.get("model_aliases", base.model_aliases))
        model_caps = raw.get("model_capabilities", raw.get("models", base.model_capabilities))
        caps = raw.get("capabilities", base.capabilities)
        options = dict(base.options)
        raw_options = raw.get("options")
        if isinstance(raw_options, dict):
            options.update(raw_options)
        # Permit common browser values directly in a provider section.
        for key in (
            "browser", "headless", "profile_dir", "auth_timeout", "connect_timeout",
            "session_timeout", "request_timeout", "executable_path",
        ):
            if key in raw:
                options[key] = raw[key]
        return ProviderDefinition(
            id=str(raw.get("id") or provider_id).strip() or provider_id,
            type=ptype,
            enabled=_bool(raw.get("enabled"), base.enabled),
            base_url=_normalise_url(raw.get("base_url", base.base_url)),
            api_key_env=str(raw.get("api_key_env", base.api_key_env) or "").strip(),
            # ``api_key`` is supported for non-interactive deployments but is
            # intentionally never returned by provider APIs or logs.
            api_key=str(raw.get("api_key", base.api_key) or "").strip(),
            default_model=str(raw.get("default_model", raw.get("model", base.default_model)) or "").strip(),
            model_aliases=dict(aliases) if isinstance(aliases, dict) else dict(base.model_aliases),
            model_capabilities=dict(model_caps) if isinstance(model_caps, dict) else dict(base.model_capabilities),
            capabilities=dict(caps) if isinstance(caps, dict) else dict(base.capabilities),
            max_concurrent_requests=max(
                0,
                int(raw.get("max_concurrent_requests", base.max_concurrent_requests) or 0),
            ),
            options=options,
        )

    @property
    def provider_definitions(self) -> Dict[str, ProviderDefinition]:
        self._ensure_loaded()
        if self._provider_definitions is not None:
            return dict(self._provider_definitions)
        definitions = self._builtin_definitions()
        root = self._load_provider_toml()
        providers = root.get("providers", {}) if isinstance(root, dict) else {}
        if isinstance(providers, dict):
            for provider_id, raw in providers.items():
                if not isinstance(raw, dict):
                    continue
                pid = str(provider_id).strip()
                if not pid:
                    continue
                fallback = definitions.get(pid)
                definition = self._provider_from_mapping(pid, raw, fallback)
                definitions[definition.id] = definition
                if definition.id != pid:
                    definitions.pop(pid, None)
        self._provider_definitions = definitions
        return dict(definitions)

    @property
    def routing(self) -> RoutingConfig:
        self._ensure_loaded()
        if self._routing is not None:
            return self._routing
        root = self._load_provider_toml()
        raw = root.get("routing", {}) if isinstance(root, dict) else {}
        raw = raw if isinstance(raw, dict) else {}
        routes = raw.get("model_routes", raw.get("models", {}))
        aliases = raw.get("aliases", {})
        env_routes = _json_mapping(os.getenv("FREE_CODEX_MODEL_ROUTES", ""))
        env_routes.update(_json_mapping(os.getenv("FREE_CODEX_ROUTING_JSON", "")))
        env_aliases = _json_mapping(os.getenv("FREE_CODEX_MODEL_ALIASES", ""))
        merged_routes = dict(routes) if isinstance(routes, dict) else {}
        merged_routes.update(env_routes)
        merged_aliases = dict(aliases) if isinstance(aliases, dict) else {}
        merged_aliases.update(env_aliases)
        fallback = raw.get("fallback_providers", [])
        if isinstance(fallback, str):
            fallback = [p.strip() for p in fallback.split(",") if p.strip()]
        self._routing = RoutingConfig(
            default_provider=(
                os.getenv("FREE_CODEX_DEFAULT_PROVIDER")
                or str(raw.get("default_provider") or "nvidia")
            ).strip(),
            model_routes={str(k): str(v) for k, v in merged_routes.items()},
            aliases={str(k): str(v) for k, v in merged_aliases.items()},
            fallback_providers=[str(p) for p in fallback] if isinstance(fallback, list) else [],
            sticky_sessions=_bool(raw.get("sticky_sessions"), True),
        )
        return self._routing

    @property
    def default_provider(self) -> str:
        return self.routing.default_provider

    @property
    def default_provider_type(self) -> ProviderType:
        provider = self.provider_definitions.get(self.default_provider)
        if provider:
            return provider.type
        return ProviderType.normalize(self.default_provider)

    @property
    def puter_web_profile_dir(self) -> Path:
        definition = self.provider_definitions.get("puter_web")
        raw = ""
        if definition:
            raw = str(definition.options.get("profile_dir") or "")
        if not raw:
            from .free_codex_paths import free_codex_dir
            return free_codex_dir() / "puter-profile"
        return Path(raw).expanduser()

    @property
    def puter_web_enabled(self) -> bool:
        return bool(self.provider_definitions.get("puter_web", ProviderDefinition("puter_web", ProviderType.PUTER_WEB)).enabled)

    @property
    def puter_web_model(self) -> str:
        definition = self.provider_definitions.get("puter_web")
        return definition.default_model if definition else ""

    def _puter_option(self, key: str, default: Any) -> Any:
        definition = self.provider_definitions.get("puter_web")
        if not definition:
            return default
        return definition.options.get(key, default)

    @property
    def puter_web_browser(self) -> str:
        return str(self._puter_option("browser", "chromium"))

    @property
    def puter_web_headless(self) -> bool:
        return _bool(self._puter_option("headless", True), True)

    def _puter_int_option(self, key: str, default: int, minimum: int) -> int:
        try:
            return max(minimum, int(self._puter_option(key, default)))
        except (TypeError, ValueError):
            return default

    @property
    def puter_web_auth_timeout(self) -> int:
        return self._puter_int_option("auth_timeout", 300, 1)

    @property
    def puter_web_connect_timeout(self) -> int:
        return self._puter_int_option("connect_timeout", 30, 1)

    @property
    def puter_web_session_timeout(self) -> int:
        return self._puter_int_option("session_timeout", 3600, 30)

    @property
    def puter_web_request_timeout(self) -> int:
        return self._puter_int_option("request_timeout", 900, 10)

    @property
    def puter_web_max_concurrent_requests(self) -> int:
        definition = self.provider_definitions.get("puter_web")
        try:
            return max(1, int(definition.max_concurrent_requests or 1)) if definition else 1
        except (TypeError, ValueError):
            return 1

    def reload(self) -> None:
        self._loaded = False
        self._cached.clear()
        self._validation_errors.clear()
        self._provider_definitions = None
        self._routing = None

    def to_dict(self) -> Dict[str, Any]:
        self._ensure_loaded()
        legacy_provider: Dict[str, Any] = {"preset": self.provider_preset.value}
        try:
            legacy_provider.update({"base_url": self.nim_base_url, "model": self.nim_model})
        except ValueError:
            pass
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
            "provider": legacy_provider,
            "providers": {k: v.to_dict() for k, v in self.provider_definitions.items()},
            "routing": self.routing.to_dict(),
            "workspace": {
                "enabled": self.workspace.enabled,
                "snippet_bytes": self.workspace.snippet_bytes,
                "snippet_lines": self.workspace.snippet_lines,
            },
            "is_valid": self.is_valid,
            "validation_errors": self.validation_errors,
        }


settings = Settings()
