from .cli_codex import resolve_codex_executable, run_codex
from .cli_server import run_server
from .utils.init_logic import fc_init as init_logic


def fc_init() -> None:
    """Initializes ~/.config/free-codex (config.toml + .env)."""
    init_logic()
