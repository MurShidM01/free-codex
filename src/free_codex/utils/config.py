import os
from dotenv import load_dotenv

from .free_codex_paths import free_codex_dotenv


class Settings:
    def __init__(self):
        self.load_settings()

    def load_settings(self) -> None:
        load_dotenv()
        env_path = free_codex_dotenv()
        if env_path.exists():
            load_dotenv(dotenv_path=env_path, override=True)

    @property
    def server_host(self) -> str:
        return os.getenv("FREE_CODEX_HOST", "0.0.0.0")

    @property
    def server_port(self) -> int:
        return int(os.getenv("FREE_CODEX_PORT", "8080"))

    @property
    def access_log_requests(self) -> bool:
        return os.getenv("FREE_CODEX_ACCESS_LOG", "0") == "1"

    @property
    def nim_base_url(self) -> str:
        return self._get_env_or_raise("NVIDIA_NIM_BASE_URL")

    @property
    def nim_api_key(self) -> str:
        return self._get_env_or_raise("NVIDIA_NIM_API_KEY")

    @property
    def nim_model(self) -> str:
        return self._get_env_or_raise("NVIDIA_NIM_MODEL")

    def _get_env_or_raise(self, key: str) -> str:
        val = os.getenv(key)
        if not val:
            raise ValueError(f"Missing required environment variable: {key}")
        return val


settings = Settings()
