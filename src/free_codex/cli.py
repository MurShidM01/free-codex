"""Console entrypoints."""

from __future__ import annotations

import argparse

from .cli_codex import resolve_codex_executable, run_codex
from .cli_puter import run_puter_auth
from .cli_server import run_server
from .utils.init_logic import fc_init as init_logic


def fc_init() -> None:
    """Initialize local proxy and multi-provider configuration."""
    parser = argparse.ArgumentParser(prog="fc-init")
    parser.add_argument(
        "--provider",
        choices=["nvidia", "nvidia-nim", "ollama", "local", "custom-openai", "puter-web"],
        help="Select the default upstream provider while keeping Codex on the local proxy.",
    )
    parser.add_argument("--model", help="Default model for the selected provider.")
    parser.add_argument("--interactive", action="store_true", help="Show the provider selection menu.")
    args = parser.parse_args()
    init_logic(provider=args.provider, model=args.model, interactive=args.interactive)


__all__ = ["fc_init", "run_server", "run_codex", "run_puter_auth", "resolve_codex_executable"]
