import os
from dotenv import load_dotenv

from .free_codex_paths import free_codex_dotenv


class Settings:
    def __init__(self):
        self._cached: dict[str, str | None] = {}
        self._loaded = False

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        load_dotenv()
        env_path = free_codex_dotenv()
        if env_path.exists():
            load_dotenv(dotenv_path=env_path, override=True)

    def _get_env(self, key: str, required: bool = True) -> str | None:
        self._ensure_loaded()
        if key in self._cached:
            return self._cached[key]
        val = os.getenv(key) or None
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


settings = Settings()